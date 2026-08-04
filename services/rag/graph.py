"""RAG as a LangGraph StateGraph.

Same retrieve -> generate flow as ask.py, but modeled as an explicit graph. This
is the linear base we grow into an agentic (self-correcting) graph in R5.

Usage: python graph.py "your question"
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

client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
db = firestore.Client(project=PROJECT)


# The shared state that flows through the graph. A node returns a partial dict,
# and LangGraph merges it into this state before the next node runs.
class RagState(TypedDict):
    question: str
    chunks: list[dict]
    answer: str


def retrieve_node(state: RagState) -> dict:
    """Embed the question, return the nearest chunks."""
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
        )
        .get()
    )
    return {"chunks": [s.to_dict() for s in snaps]}


def generate_node(state: RagState) -> dict:
    """Answer the question grounded only in the retrieved chunks."""
    context = "\n\n".join(
        f"[{c['doc_id']} #{c['chunk_index']}] {c['text']}" for c in state["chunks"]
    )
    prompt = (
        "Answer using ONLY the context below, and cite the [source #] you used. "
        "If the answer is not in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {state['question']}"
    )
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    return {"answer": resp.text}


# Assemble the graph: two nodes wired START -> retrieve -> generate -> END.
builder = StateGraph(RagState)
builder.add_node("retrieve", retrieve_node)
builder.add_node("generate", generate_node)
builder.add_edge(START, "retrieve")
builder.add_edge("retrieve", "generate")
builder.add_edge("generate", END)
graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({"question": sys.argv[1]})
    print("answer:\n" + result["answer"])
