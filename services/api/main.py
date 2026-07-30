"""DocIntel API — FastAPI service: Gemini Q&A + async document upload on GCP.

/upload is now asynchronous: it stores the file and records it as "processing",
then returns immediately. A Cloud Function (services/processor) does the Gemini
analysis out-of-band and flips the record to "done".
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai
from google.cloud import storage, firestore

STATIC_DIR = Path(__file__).parent / "static"

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
BUCKET = os.environ.get("BUCKET", "docintel-srg-2026-uploads")

client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
storage_client = storage.Client(project=PROJECT)
bucket = storage_client.bucket(BUCKET)
db = firestore.Client(project=PROJECT)

app = FastAPI(title="DocIntel API", version="0.4.0")


class AskRequest(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the web UI (single self-contained page)."""
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    """Health check — used by uptime checks / monitoring.

    Note: intentionally NOT /healthz — Google's Front End reserves that path and
    intercepts it before it reaches the container (requests 404 without hitting the app).
    """
    return {"status": "ok", "service": "docintel-api", "model": MODEL, "bucket": BUCKET}


@app.post("/ask")
def ask(req: AskRequest):
    """Send a free-form question to Gemini and return the answer."""
    response = client.models.generate_content(model=MODEL, contents=req.question)
    return {"question": req.question, "answer": response.text}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Store the file + a 'processing' record, then return instantly.

    Uploading the object fires a GCS event -> Pub/Sub -> the processor function,
    which analyzes it and merges the results into this same record.
    """
    data = await file.read()
    content_type = file.content_type or "text/plain"
    doc_id = uuid.uuid4().hex
    object_name = f"uploads/{doc_id}/{file.filename}"
    bucket.blob(object_name).upload_from_string(data, content_type=content_type)

    record = {
        "filename": file.filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "gcs_uri": f"gs://{BUCKET}/{object_name}",
        "uploaded_at": datetime.now(timezone.utc),
        "status": "processing",
    }
    db.collection("documents").document(doc_id).set(record)
    return {"id": doc_id, **record}


@app.get("/documents")
def list_documents():
    """List all documents, newest first."""
    docs = (
        db.collection("documents")
        .order_by("uploaded_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    return [{"id": d.id, **d.to_dict()} for d in docs]


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    """Fetch one document's full record by ID."""
    snap = db.collection("documents").document(doc_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="document not found")
    return {"id": snap.id, **snap.to_dict()}


@app.post("/tasks/stats")
def refresh_stats():
    """Tally documents into a stats summary and store it. Called on a schedule by Cloud Scheduler."""
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    total = 0
    for d in db.collection("documents").stream():
        data = d.to_dict()
        total += 1
        status = data.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        doc_type = data.get("doc_type")
        if doc_type:
            by_type[doc_type] = by_type.get(doc_type, 0) + 1

    summary = {
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
        "computed_at": datetime.now(timezone.utc),
    }
    db.collection("stats").document("summary").set(summary)
    print(f"Stats refreshed: total={total} status={by_status} type={by_type}")
    return summary


@app.get("/stats")
def get_stats():
    """Read the most recent stats summary."""
    snap = db.collection("stats").document("summary").get()
    return snap.to_dict() if snap.exists else {"total": 0, "note": "no stats computed yet"}
