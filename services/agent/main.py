"""FastAPI wrapper exposing the tool-using agent as an HTTP endpoint + chat UI."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent import run_agent

STATIC_DIR = Path(__file__).parent / "static"
app = FastAPI(title="DocIntel Agent", version="0.2.0")


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
    """Route the question to the agent, which picks SQL vs vector RAG itself."""
    return {"question": req.question, "answer": run_agent(req.question)}
