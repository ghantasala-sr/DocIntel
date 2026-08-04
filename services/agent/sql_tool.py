"""Text-to-SQL tool over BigQuery: natural-language question -> SQL -> rows.

Usage: python sql_tool.py "which company had the highest 2024 revenue?"
"""
import os
import re
import sys

from google import genai
from google.cloud import bigquery

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")

client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
bq = bigquery.Client(project=PROJECT)

SCHEMA = """
Table `docintel.financials` (one row per fact):
  company      STRING   -- e.g. "Northwind Traders"
  ticker       STRING   -- e.g. "NWT"
  fiscal_year  INT64    -- e.g. 2024
  metric       STRING   -- one of: "revenue", "net_income"
  value        FLOAT64  -- the amount
  unit         STRING   -- e.g. "USD"
"""


def to_sql(question: str) -> str:
    """Ask the model to turn the question into a single BigQuery SELECT."""
    prompt = (
        "You write BigQuery Standard SQL. Using ONLY the schema below, return a single "
        "SELECT query that answers the question. Return ONLY the SQL — no markdown, no prose.\n\n"
        f"{SCHEMA}\nQuestion: {question}"
    )
    sql = client.models.generate_content(model=MODEL, contents=prompt).text.strip()
    return re.sub(r"```sql|```", "", sql).strip()  # strip any code fences


def run_sql(sql: str) -> list[dict]:
    """Run a read-only query. Reject anything that isn't a SELECT (injection guard)."""
    if not sql.lstrip().lower().startswith("select"):
        raise ValueError(f"refusing non-SELECT query: {sql!r}")
    return [dict(row) for row in bq.query(sql).result()]


def sql_tool(question: str) -> list[dict]:
    """The callable tool: question in, rows out."""
    sql = to_sql(question)
    print(f"[sql]\n{sql}")
    return run_sql(sql)


if __name__ == "__main__":
    rows = sql_tool(sys.argv[1])
    print(f"[rows] {rows}")
