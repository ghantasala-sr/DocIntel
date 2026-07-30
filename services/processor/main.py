"""DocIntel processor — Cloud Function (2nd gen) triggered by Pub/Sub.

Consumes the GCS OBJECT_FINALIZE event published when a file lands in the bucket,
runs Gemini analysis, and merges the results into the document's Firestore record.
"""
import base64
import json
import os
from datetime import datetime, timezone

import functions_framework
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.cloud import firestore

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")

client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
db = firestore.Client(project=PROJECT)

ANALYSIS_PROMPT = (
    "You are a document analyst. Analyze the attached document and produce: "
    "a concise 2-3 sentence summary; up to 6 key entities (people, "
    "organizations, dates, monetary amounts, locations); and a short "
    "document-type label (e.g. invoice, resume, contract, article, email)."
)


class DocAnalysis(BaseModel):
    summary: str
    entities: list[str]
    doc_type: str


@functions_framework.cloud_event
def process_upload(cloud_event):
    # The Pub/Sub message rides inside the CloudEvent; its data is the base64
    # GCS object metadata JSON we saw when we pulled the queue by hand.
    message = cloud_event.data["message"]
    obj = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
    bucket_name = obj["bucket"]
    object_name = obj["name"]
    content_type = obj.get("contentType", "text/plain")

    # Only process API uploads shaped as uploads/{doc_id}/{filename}; ignore the rest.
    parts = object_name.split("/")
    if len(parts) < 3 or parts[0] != "uploads":
        print(f"Skipping non-upload object: {object_name}")
        return

    doc_id = parts[1]
    gcs_uri = f"gs://{bucket_name}/{object_name}"
    print(f"Processing {gcs_uri} -> doc {doc_id}")

    response = client.models.generate_content(
        model=MODEL,
        contents=[types.Part.from_uri(file_uri=gcs_uri, mime_type=content_type), ANALYSIS_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DocAnalysis,
        ),
    )
    analysis: DocAnalysis = response.parsed

    # merge=True: update the existing record (written by the API) without clobbering it.
    db.collection("documents").document(doc_id).set(
        {
            "summary": analysis.summary,
            "entities": analysis.entities,
            "doc_type": analysis.doc_type,
            "status": "done",
            "processed_at": datetime.now(timezone.utc),
        },
        merge=True,
    )
    print(f"Done doc {doc_id}: {analysis.doc_type}")
