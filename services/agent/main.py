"""FastAPI wrapper exposing the tool-using agent as an HTTP endpoint."""
from fastapi import FastAPI
from pydantic import BaseModel

from agent import run_agent

app = FastAPI(title="DocIntel Agent", version="0.1.0")


class AskRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "docintel-agent"}


@app.post("/agent")
def ask_agent(req: AskRequest):
    """Route the question to the agent, which picks SQL vs vector RAG itself."""
    return {"question": req.question, "answer": run_agent(req.question)}
