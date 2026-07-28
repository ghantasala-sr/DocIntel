"""DocIntel API — a FastAPI service exposing a Gemini-backed /ask endpoint."""
import os

# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from pydantic import BaseModel
from google import genai

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")

# One client, created once at startup and reused across requests.
client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)

app = FastAPI(title="DocIntel API", version="0.1.0")


class AskRequest(BaseModel):
    question: str


@app.get("/")
def health():
    """Health check — Cloud Run and load balancers hit this to see if we're alive."""
    return {"status": "ok", "service": "docintel-api", "model": MODEL}


@app.post("/ask")
def ask(req: AskRequest):
    """Send a question to Gemini and return the answer."""
    response = client.models.generate_content(model=MODEL, contents=req.question)
    return {"question": req.question, "answer": response.text}
