"""DocIntel API — FastAPI service: Gemini Q&A + async document upload on GCP.

/upload is now asynchronous: it stores the file and records it as "processing",
then returns immediately. A Cloud Function (services/processor) does the Gemini
analysis out-of-band and flips the record to "done".
"""
import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from google import genai
from google.cloud import storage, firestore

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
BUCKET = os.environ.get("BUCKET", "docintel-srg-2026-uploads")

client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
storage_client = storage.Client(project=PROJECT)
bucket = storage_client.bucket(BUCKET)
db = firestore.Client(project=PROJECT)

app = FastAPI(title="DocIntel API", version="0.3.0")


class AskRequest(BaseModel):
    question: str


@app.get("/")
def health():
    """Health check — Cloud Run pings this to see if we're alive."""
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
