"""A tool-using agent over real CFPB consumer complaints:
  - query_complaints: text-to-SQL over BigQuery `docintel.cfpb_complaints` (facts)
  - search_complaints: vector RAG over the complaint narratives (what people said)

Usage: python cfpb_agent.py "your question"
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
Table `docintel.cfpb_complaints` (one row per complaint):
  complaint_id STRING, date_received TIMESTAMP, product STRING, sub_product STRING,
  issue STRING, company STRING, state STRING, company_response STRING
"""

SYSTEM_PROMPT = (
    "You are a CFPB consumer-complaints assistant (mortgage complaints). Use:\n"
    "- query_complaints: counts, rankings, trends by company, state, issue, or date.\n"
    "- search_complaints: what consumers actually describe (themes, examples).\n"
    "Cite the company/issue from search results or the figures from queries. If the "
    "tools return nothing relevant, say you don't have enough data. Never invent facts."
)


@tool
def query_complaints(question: str) -> str:
    """Query structured mortgage-complaint FACTS: counts, rankings, trends by company,
    state, issue, sub_product, or date. Use for 'how many', 'which company', 'top', etc."""
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


@tool
def search_complaints(query: str) -> str:
    """Search what consumers actually WROTE in their complaint narratives — themes,
    specific problems, examples. Use for 'what do people say/complain about ...'."""
    qvec = genai_client.models.embed_content(
        model=EMBED_MODEL, contents=query
    ).embeddings[0].values
    snaps = (
        db.collection("chunks")
        .find_nearest(
            vector_field="embedding",
            query_vector=Vector(qvec),
            distance_measure=DistanceMeasure.COSINE,
            limit=6,
        )
        .get()
    )
    docs = [d for d in (s.to_dict() for s in snaps) if d.get("source") == "cfpb"][:4]
    if not docs:
        return "no relevant complaints found"
    return "\n\n".join(
        f"[{d.get('company')} · {d.get('issue')}] {d.get('text', '')[:500]}" for d in docs
    )


llm = ChatVertexAI(model=MODEL, project=PROJECT, location=LOCATION, temperature=0)
agent = create_react_agent(llm, tools=[query_complaints, search_complaints])


def run_agent(question: str) -> str:
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
