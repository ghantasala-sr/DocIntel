"""FastAPI wrapper exposing the agents as HTTP endpoints (+ its own chat UI).

CORS is open so the DocIntel dashboard (served by the API on a different origin)
can call /agent and /cfpb.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent import run_agent

STATIC_DIR = Path(__file__).parent / "static"
app = FastAPI(title="DocIntel Agent", version="0.3.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class AskRequest(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the chat UI."""
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok", "service": "docintel-agent"}


@app.post("/agent")
def ask_agent(req: AskRequest):
    """Financial agent — routes text-to-SQL (BigQuery) vs vector RAG (documents)."""
    return {"question": req.question, "answer": run_agent(req.question)}


@app.post("/cfpb")
def ask_cfpb(req: AskRequest):
    """CFPB consumer-complaints agent (lazy-imported on first call to keep startup light)."""
    from cfpb_agent import run_agent as run_cfpb

    return {"question": req.question, "answer": run_cfpb(req.question)}
