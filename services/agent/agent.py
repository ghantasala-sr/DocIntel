"""A hardened tool-using agent (LangGraph create_react_agent) over two tools:
  - search_documents: vector RAG over uploaded docs (qualitative questions)
  - query_financials: text-to-SQL over BigQuery (exact numbers)

The model decides which tool(s) to call. A system prompt enforces tool choice,
source citation, and abstention instead of fabrication.

Usage: python agent.py "your question"
"""
import os
import re
import sys

from google import genai
from google.cloud import firestore, bigquery
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

from langchain_core.tools import tool
from langchain_google_vertexai import ChatVertexAI
from langgraph.prebuilt import create_react_agent

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-005")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")

genai_client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
db = firestore.Client(project=PROJECT)
bq = bigquery.Client(project=PROJECT)

SCHEMA = """
Table `docintel.financials` (one row per fact):
  company STRING, ticker STRING, fiscal_year INT64,
  metric STRING (one of "revenue","net_income"), value FLOAT64, unit STRING
"""

SYSTEM_PROMPT = (
    "You are DocIntel's assistant. Answer only from your tools:\n"
    "- query_financials: exact company financials (revenue, net_income; totals, comparisons, growth).\n"
    "- search_documents: qualitative/textual info (policies, how things work, descriptions).\n"
    "Cite your sources: the [doc #chunk] tags from documents, or the figures returned by "
    "query_financials. If the tools return nothing relevant, say you don't have enough "
    "information to answer. Never invent facts or numbers."
)


@tool
def search_documents(query: str) -> str:
    """Search uploaded documents (handbooks, policies, descriptions) for QUALITATIVE
    or textual information — how something works, policies, explanations. Not for numbers."""
    qvec = genai_client.models.embed_content(
        model=EMBED_MODEL, contents=query
    ).embeddings[0].values
    snaps = (
        db.collection("chunks")
        .find_nearest(
            vector_field="embedding",
            query_vector=Vector(qvec),
            distance_measure=DistanceMeasure.COSINE,
            limit=3,
        )
        .get()
    )
    docs = [s.to_dict() for s in snaps]
    return (
        "\n\n".join(f"[{d['doc_id']} #{d['chunk_index']}] {d['text']}" for d in docs)
        or "no relevant documents found"
    )


@tool
def query_financials(question: str) -> str:
    """Query the structured financials table for EXACT numbers — revenue and net_income
    by company and fiscal_year. Use for quantitative/analytical questions: totals,
    comparisons, highest/lowest, growth."""
    prompt = (
        "You write BigQuery Standard SQL. Using ONLY this schema, return one SELECT that "
        "answers the question. Return ONLY SQL.\n\n" + SCHEMA + f"\nQuestion: {question}"
    )
    sql = re.sub(
        r"```sql|```", "", genai_client.models.generate_content(model=MODEL, contents=prompt).text
    ).strip()
    if not sql.lstrip().lower().startswith("select"):
        return f"refused non-SELECT query: {sql}"
    rows = [dict(r) for r in bq.query(sql).result()]
    return f"SQL used: {sql}\nResult rows: {rows}"


llm = ChatVertexAI(model=MODEL, project=PROJECT, location=LOCATION, temperature=0)
agent = create_react_agent(llm, tools=[search_documents, query_financials])


def run_agent(question: str) -> str:
    """Run the agent and return the final answer text (used by the API)."""
    result = agent.invoke(
        {"messages": [("system", SYSTEM_PROMPT), ("user", question)]},
        config={"recursion_limit": 8},
    )
    return result["messages"][-1].content


if __name__ == "__main__":
    result = agent.invoke(
        {"messages": [("system", SYSTEM_PROMPT), ("user", sys.argv[1])]},
        config={"recursion_limit": 8},
    )
    for message in result["messages"]:
        message.pretty_print()
