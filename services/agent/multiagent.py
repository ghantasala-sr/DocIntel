"""A supervisor multi-agent system (LangGraph) with 6 agents:
  supervisor (router) + financials_analyst, complaints_analyst, document_librarian,
  general_assistant (ReAct specialists) + synthesizer (final answer).

The supervisor routes each turn to specialists, loops until it has enough, then the
synthesizer writes the answer. Conversation memory comes from the message list passed
in (persisted per thread in Firestore by threads.py).

Usage: python multiagent.py "your question"
"""
import operator
import os
import re
import sys
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel

from google import genai
from google.cloud import firestore, bigquery
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_google_vertexai import ChatVertexAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-005")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")

genai_client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
db = firestore.Client(project=PROJECT)
bq = bigquery.Client(project=PROJECT)
llm = ChatVertexAI(model=MODEL, project=PROJECT, location=LOCATION, temperature=0)

FIN_SCHEMA = "Table `docintel.financials`: company STRING, ticker STRING, fiscal_year INT64, metric STRING ('revenue'|'net_income'), value FLOAT64, unit STRING"
CFPB_SCHEMA = "Table `docintel.cfpb_complaints`: complaint_id STRING, date_received TIMESTAMP, product STRING, sub_product STRING, issue STRING, company STRING, state STRING, company_response STRING"


def _sql(schema: str, table_hint: str, question: str) -> str:
    prompt = f"You write BigQuery Standard SQL. Using ONLY this schema, return one SELECT answering the question. Return ONLY SQL.\n\n{schema}\nQuestion: {question}"
    sql = re.sub(r"```sql|```", "", genai_client.models.generate_content(model=MODEL, contents=prompt).text).strip()
    if not sql.lstrip().lower().startswith("select"):
        return f"refused non-SELECT: {sql}"
    return f"SQL: {sql}\nRows: {[dict(r) for r in bq.query(sql).result()]}"


def _search(query: str, want_cfpb: bool) -> str:
    qvec = genai_client.models.embed_content(model=EMBED_MODEL, contents=query).embeddings[0].values
    snaps = db.collection("chunks").find_nearest(
        vector_field="embedding", query_vector=Vector(qvec),
        distance_measure=DistanceMeasure.COSINE, limit=8).get()
    docs = [d for d in (s.to_dict() for s in snaps) if (d.get("source") == "cfpb") == want_cfpb][:4]
    if not docs:
        return "no relevant results"
    return "\n\n".join(f"[{d.get('company') or d.get('doc_id')} · {d.get('issue','')}] {d.get('text','')[:400]}" for d in docs)


@tool
def query_financials(question: str) -> str:
    """Exact company financials (revenue, net_income) by company and fiscal_year."""
    return _sql(FIN_SCHEMA, "financials", question)


@tool
def query_complaints(question: str) -> str:
    """Counts/rankings/trends of CFPB mortgage complaints by company, state, issue, date."""
    return _sql(CFPB_SCHEMA, "cfpb_complaints", question)


@tool
def search_complaints(query: str) -> str:
    """What consumers actually wrote in CFPB complaint narratives (themes, examples)."""
    return _search(query, want_cfpb=True)


@tool
def search_documents(query: str) -> str:
    """Qualitative info from uploaded documents / the product handbook (not complaints)."""
    return _search(query, want_cfpb=False)


# Four ReAct specialists (agents 2–5).
financials_analyst = create_react_agent(llm, [query_financials])
complaints_analyst = create_react_agent(llm, [query_complaints, search_complaints])
document_librarian = create_react_agent(llm, [search_documents])
general_assistant = create_react_agent(llm, [])  # no tools: general knowledge

MEMBERS = ["financials_analyst", "complaints_analyst", "document_librarian", "general_assistant"]
SPECIALISTS = {
    "financials_analyst": financials_analyst,
    "complaints_analyst": complaints_analyst,
    "document_librarian": document_librarian,
    "general_assistant": general_assistant,
}


class State(TypedDict):
    messages: Annotated[list, add_messages]
    next: str
    visited: Annotated[list, operator.add]  # specialists already consulted this turn


class Route(BaseModel):
    next: Literal["financials_analyst", "complaints_analyst", "document_librarian", "general_assistant", "synthesize"]


def supervisor_node(state: State) -> dict:  # agent 1
    visited = state.get("visited", [])
    sys = (
        "You are a supervisor routing the user's request to specialists:\n"
        "- financials_analyst: company revenue/net_income facts.\n"
        "- complaints_analyst: CFPB mortgage complaints (counts + what people say).\n"
        "- document_librarian: uploaded documents / product handbook.\n"
        "- general_assistant: general knowledge or conversation.\n"
        f"Specialists already consulted this turn (do NOT pick these again): {visited}. "
        "If their responses in the conversation now answer the question, choose 'synthesize'. "
        "Route to the fewest specialists needed."
    )
    route = llm.with_structured_output(Route).invoke([("system", sys)] + state["messages"]).next
    # Hard guard against loops: never repeat a specialist; cap total specialists per turn.
    if route in visited or len(visited) >= 3:
        route = "synthesize"
    print(f"[supervisor] -> {route}")
    return {"next": route}


def make_worker(name: str):
    agent = SPECIALISTS[name]

    def node(state: State) -> dict:
        result = agent.invoke({"messages": state["messages"]})
        msgs = result["messages"]
        # Surface the RAW tool outputs (SQL rows, retrieved text) — the ground truth —
        # plus the specialist's summary, so the synthesizer can't hallucinate over them.
        tool_data = [m.content for m in msgs if getattr(m, "type", "") == "tool"]
        block = f"[{name}]"
        if tool_data:
            block += "\nTool results (ground truth):\n" + "\n".join(tool_data)
        block += f"\nSummary: {msgs[-1].content}"
        print(f"[{name}] responded ({len(tool_data)} tool result(s))")
        return {"messages": [AIMessage(content=block, name=name)], "visited": [name]}

    return node


def synthesize_node(state: State) -> dict:  # agent 6
    sys = (
        "You are the final responder. Answer the user's latest question using ONLY facts, "
        "numbers, and names that appear explicitly in the specialist messages in this "
        "conversation. You must NOT use any outside or prior knowledge about companies, "
        "figures, or events. Do NOT invent, round, or estimate numbers. If a fact or figure "
        "is not present in the specialists' messages, do not state it. If the specialists did "
        "not find the answer, say the information is not available in the data. Quote the "
        "specialists' figures exactly as given."
    )
    answer = llm.invoke([("system", sys)] + state["messages"]).content
    return {"messages": [AIMessage(content=answer, name="synthesizer")]}


builder = StateGraph(State)
builder.add_node("supervisor", supervisor_node)
for m in MEMBERS:
    builder.add_node(m, make_worker(m))
builder.add_node("synthesize", synthesize_node)
builder.add_edge(START, "supervisor")
builder.add_conditional_edges("supervisor", lambda s: s["next"])
for m in MEMBERS:
    builder.add_edge(m, "supervisor")
builder.add_edge("synthesize", END)
graph = builder.compile()


def run_multiagent(messages: list) -> str:
    """Run the supervisor graph over a message list; return the final answer text."""
    result = graph.invoke({"messages": messages, "visited": []}, config={"recursion_limit": 12})
    return result["messages"][-1].content


if __name__ == "__main__":
    print("\nANSWER:\n" + run_multiagent([HumanMessage(content=sys.argv[1])]))
