"""FastAPI backend: threaded multi-agent chat (+ CORS for the dashboard).

The supervisor multi-agent routes each turn to specialists (financials, complaints,
documents, general) and synthesizes a grounded answer; threads.py persists memory.
"""
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from threads import chat, get_thread, list_threads

app = FastAPI(title="DocIntel Multi-Agent", version="0.4.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "service": "docintel-multiagent"}


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    """Send a message; the multi-agent answers with memory of the thread."""
    return chat(req.thread_id, req.message)


@app.get("/threads")
def threads_endpoint():
    """List recent conversation threads (for the sidebar)."""
    return list_threads()


@app.get("/threads/{thread_id}")
def thread_endpoint(thread_id: str):
    """Fetch one thread's message history."""
    return get_thread(thread_id)
