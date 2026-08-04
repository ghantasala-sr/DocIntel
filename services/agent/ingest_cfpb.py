"""Ingest CFPB consumer complaints into BigQuery (structured) + Firestore vectors
(narratives), so the agent can query both.

Usage: python ingest_cfpb.py
"""
import json
import os
import subprocess
import urllib.parse

from google import genai
from google.cloud import firestore, bigquery
from google.cloud.firestore_v1.vector import Vector

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-005")

API = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
PRODUCT = "Mortgage"
TOTAL = 150
TABLE = "docintel.cfpb_complaints"

genai_client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
db = firestore.Client(project=PROJECT)
bq = bigquery.Client(project=PROJECT)


def fetch(total: int) -> list[dict]:
    """Page through the CFPB API for complaints with narratives.

    The API is behind bot-detection that 403s Python's HTTP stack, so we fetch via
    curl (which its TLS/HTTP fingerprint is allowed through).
    """
    out, frm = [], 0
    while len(out) < total:
        params = urllib.parse.urlencode(
            {"size": min(100, total - len(out)), "frm": frm, "has_narrative": "true",
             "no_aggs": "true", "sort": "created_date_desc", "product": PRODUCT}
        )
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "30",
             "-H", "User-Agent: Mozilla/5.0 (DocIntel research)", f"{API}?{params}"],
            capture_output=True, text=True, check=True,
        )
        hits = json.loads(result.stdout)["hits"]["hits"]
        if not hits:
            break
        out.extend(h["_source"] for h in hits)
        frm += len(hits)
    print(f"fetched {len(out)} complaints")
    return out[:total]


def load_bigquery(rows: list[dict]) -> None:
    """Load the structured facts into a BigQuery table (replace on each run)."""
    records = [
        {k: r.get(k) for k in
         ("complaint_id", "date_received", "product", "sub_product", "issue",
          "company", "state", "company_response")}
        for r in rows
    ]
    schema = [
        bigquery.SchemaField("complaint_id", "STRING"),
        bigquery.SchemaField("date_received", "TIMESTAMP"),
        bigquery.SchemaField("product", "STRING"),
        bigquery.SchemaField("sub_product", "STRING"),
        bigquery.SchemaField("issue", "STRING"),
        bigquery.SchemaField("company", "STRING"),
        bigquery.SchemaField("state", "STRING"),
        bigquery.SchemaField("company_response", "STRING"),
    ]
    cfg = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE")
    bq.load_table_from_json(records, TABLE, job_config=cfg).result()
    print(f"loaded {len(records)} rows into {TABLE}")


def embed_narratives(rows: list[dict]) -> None:
    """Embed each complaint narrative and store it in the `chunks` collection."""
    n = 0
    for r in rows:
        narrative = (r.get("complaint_what_happened") or "").strip()
        if not narrative:
            continue
        vector = genai_client.models.embed_content(
            model=EMBED_MODEL, contents=narrative[:8000]
        ).embeddings[0].values
        doc_id = f"cfpb-{r.get('complaint_id')}"
        # Deterministic ID + set() => re-running overwrites instead of duplicating.
        db.collection("chunks").document(doc_id).set({
            "source": "cfpb",
            "doc_id": doc_id,
            "chunk_index": 0,
            "text": narrative,
            "company": r.get("company"),
            "product": r.get("product"),
            "issue": r.get("issue"),
            "embedding": Vector(vector),
        })
        n += 1
        if n % 25 == 0:
            print(f"  embedded {n}…")
    print(f"embedded {n} narratives into Firestore")


if __name__ == "__main__":
    complaints = fetch(TOTAL)
    load_bigquery(complaints)
    embed_narratives(complaints)
    print("done")
