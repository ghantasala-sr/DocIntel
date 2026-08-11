"""Firestore-backed chat threads — persistent conversation memory for the
multi-agent. Each thread is a doc in `chat_threads` holding its message list;
every turn replays the history so the agents have context.
"""
import os
import uuid
from datetime import datetime, timezone

from google.cloud import firestore
from langchain_core.messages import AIMessage, HumanMessage

from multiagent import run_multiagent

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
db = firestore.Client(project=PROJECT)
COLL = "chat_threads"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_threads() -> list[dict]:
    """Recent threads (id + title), newest first — for the sidebar."""
    docs = (
        db.collection(COLL)
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(50)
        .stream()
    )
    return [{"id": d.id, "title": d.to_dict().get("title", "New chat")} for d in docs]


def get_thread(thread_id: str) -> dict:
    """A thread's full message history."""
    snap = db.collection(COLL).document(thread_id).get()
    if not snap.exists:
        return {}
    d = snap.to_dict()
    return {"id": snap.id, "title": d.get("title"), "messages": d.get("messages", [])}


def chat(thread_id: str | None, message: str) -> dict:
    """Append a user message, run the multi-agent over the whole thread, persist, return."""
    ref = (
        db.collection(COLL).document(thread_id)
        if thread_id
        else db.collection(COLL).document(uuid.uuid4().hex)
    )
    snap = ref.get()
    data = snap.to_dict() if snap.exists else {"title": message[:48], "created_at": _now(), "messages": []}
    history = data.get("messages", [])

    # Replay history as LangChain messages so the agents remember the conversation.
    lc_messages = [
        HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"])
        for m in history
    ]
    lc_messages.append(HumanMessage(message))
    answer = run_multiagent(lc_messages)

    history += [{"role": "user", "content": message}, {"role": "assistant", "content": answer}]
    data.update(messages=history, updated_at=_now())
    ref.set(data)
    return {"thread_id": ref.id, "answer": answer}
