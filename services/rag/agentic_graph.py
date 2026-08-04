"""Agentic, self-checking RAG with LangGraph.

Two quality checks around the core retrieve/generate:
  - a retrieval-confidence gate (cosine distance) + relevance grade
  - a groundedness check on the generated answer
If retrieval is weak or the answer isn't grounded, the graph ABSTAINS instead
of hallucinating.

Flow:
  retrieve -> grade -> (relevant? generate : rewrite->retrieve, or abstain)
  generate -> check -> (grounded? END : abstain)

Usage: python agentic_graph.py "your question"
"""
import os
import sys
from typing import TypedDict

from google import genai
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from langgraph.graph import StateGraph, START, END

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-005")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
MAX_ATTEMPTS = 2
DISTANCE_THRESHOLD = 0.7  # cosine distance; higher = less similar. Tunable knob.
ABSTAIN_MSG = "I don't have enough information in the provided documents to answer that."

client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
db = firestore.Client(project=PROJECT)


class RagState(TypedDict):
    question: str
    chunks: list[dict]
    best_distance: float
    relevant: bool
    answer: str
    grounded: bool
    attempts: int


def _yesno(prompt: str) -> bool:
    return client.models.generate_content(model=MODEL, contents=prompt).text.strip().lower().startswith("y")


def retrieve_node(state: RagState) -> dict:
    qvec = client.models.embed_content(
        model=EMBED_MODEL, contents=state["question"]
    ).embeddings[0].values
    snaps = (
        db.collection("chunks")
        .find_nearest(
            vector_field="embedding",
            query_vector=Vector(qvec),
            distance_measure=DistanceMeasure.COSINE,
            limit=3,
            distance_result_field="distance",  # attaches the cosine distance to each result
        )
        .get()
    )
    chunks = [s.to_dict() for s in snaps]
    best = min((c.get("distance", 9.0) for c in chunks), default=9.0)
    print(f"[retrieve] {len(chunks)} chunks, best distance={best:.3f}")
    return {"chunks": chunks, "best_distance": best}


def grade_node(state: RagState) -> dict:
    """Gate 1: numeric distance gate first (cheap), then an LLM relevance judge."""
    if state["best_distance"] > DISTANCE_THRESHOLD:
        print(f"[grade] distance {state['best_distance']:.3f} > {DISTANCE_THRESHOLD} -> not relevant (gate)")
        return {"relevant": False}
    context = "\n\n".join(c["text"] for c in state["chunks"])
    relevant = _yesno(
        "Is the context relevant and sufficient to answer the question? Reply only yes or no.\n\n"
        f"Question: {state['question']}\n\nContext:\n{context}"
    )
    print(f"[grade] llm relevant={relevant}")
    return {"relevant": relevant}


def rewrite_node(state: RagState) -> dict:
    new_q = client.models.generate_content(
        model=MODEL,
        contents=(
            "Rewrite the question to retrieve better documents. Keep the intent; use "
            "synonyms and keywords. Return only the rewritten question.\n\n"
            f"Question: {state['question']}"
        ),
    ).text.strip()
    print(f"[rewrite] -> {new_q!r}")
    return {"question": new_q, "attempts": state.get("attempts", 0) + 1}


def generate_node(state: RagState) -> dict:
    context = "\n\n".join(
        f"[{c['doc_id']} #{c['chunk_index']}] {c['text']}" for c in state["chunks"]
    )
    answer = client.models.generate_content(
        model=MODEL,
        contents=(
            "Answer using ONLY the context below, and cite the [source #]. If the answer "
            "is not in the context, say you don't know.\n\n"
            f"Context:\n{context}\n\nQuestion: {state['question']}"
        ),
    ).text
    print("[generate] drafted answer")
    return {"answer": answer}


def check_node(state: RagState) -> dict:
    """Gate 2: is every claim in the answer supported by the retrieved context?"""
    context = "\n\n".join(c["text"] for c in state["chunks"])
    grounded = _yesno(
        "Is EVERY claim in the ANSWER supported by the CONTEXT? Reply only yes or no.\n\n"
        f"CONTEXT:\n{context}\n\nANSWER:\n{state['answer']}"
    )
    print(f"[check] grounded={grounded}")
    return {"grounded": grounded}


def abstain_node(state: RagState) -> dict:
    print("[abstain] insufficient evidence -> abstaining")
    return {"answer": ABSTAIN_MSG}


def route_after_grade(state: RagState) -> str:
    if state["relevant"]:
        return "generate"
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        return "abstain"
    return "rewrite"


def route_after_check(state: RagState):
    return END if state["grounded"] else "abstain"


builder = StateGraph(RagState)
builder.add_node("retrieve", retrieve_node)
builder.add_node("grade", grade_node)
builder.add_node("rewrite", rewrite_node)
builder.add_node("generate", generate_node)
builder.add_node("check", check_node)
builder.add_node("abstain", abstain_node)

builder.add_edge(START, "retrieve")
builder.add_edge("retrieve", "grade")
builder.add_conditional_edges("grade", route_after_grade)
builder.add_edge("rewrite", "retrieve")
builder.add_edge("generate", "check")
builder.add_conditional_edges("check", route_after_check)
builder.add_edge("abstain", END)
graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({"question": sys.argv[1], "attempts": 0})
    print("\nanswer:\n" + result["answer"])
