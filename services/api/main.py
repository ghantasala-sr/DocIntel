"""DocIntel API — FastAPI service: Gemini Q&A + document upload/analysis on GCP."""
import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.cloud import storage, firestore

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
BUCKET = os.environ.get("BUCKET", "docintel-srg-2026-uploads")

# Clients created once at startup and reused across requests.
client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
storage_client = storage.Client(project=PROJECT)
bucket = storage_client.bucket(BUCKET)
db = firestore.Client(project=PROJECT)

app = FastAPI(title="DocIntel API", version="0.2.0")

ANALYSIS_PROMPT = (
    "You are a document analyst. Analyze the attached document and produce: "
    "a concise 2-3 sentence summary; up to 6 key entities (people, "
    "organizations, dates, monetary amounts, locations); and a short "
    "document-type label (e.g. invoice, resume, contract, article, email)."
)


class AskRequest(BaseModel):
    question: str


class DocAnalysis(BaseModel):
    """The structured shape we force Gemini to return (schema-constrained output)."""
    summary: str
    entities: list[str]
    doc_type: str


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
    """Store a file in Cloud Storage, analyze it with Gemini, persist results in Firestore."""
    data = await file.read()
    content_type = file.content_type or "text/plain"
    doc_id = uuid.uuid4().hex

    # 1) Store the raw file as an object in the bucket.
    object_name = f"uploads/{doc_id}/{file.filename}"
    bucket.blob(object_name).upload_from_string(data, content_type=content_type)
    gcs_uri = f"gs://{BUCKET}/{object_name}"

    # 2) Ask Gemini to analyze the file (read straight from GCS) into a fixed schema.
    response = client.models.generate_content(
        model=MODEL,
        contents=[types.Part.from_uri(file_uri=gcs_uri, mime_type=content_type), ANALYSIS_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DocAnalysis,
        ),
    )
    analysis: DocAnalysis = response.parsed

    # 3) Persist a record about the file (not the file itself) in Firestore.
    record = {
        "filename": file.filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "gcs_uri": gcs_uri,
        "uploaded_at": datetime.now(timezone.utc),
        "summary": analysis.summary,
        "entities": analysis.entities,
        "doc_type": analysis.doc_type,
    }
    db.collection("documents").document(doc_id).set(record)
    return {"id": doc_id, **record}


@app.get("/documents")
def list_documents():
    """List all analyzed documents, newest first."""
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
