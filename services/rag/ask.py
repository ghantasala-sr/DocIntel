"""Baseline RAG: retrieve the nearest chunks to a question, answer with Gemini.

Usage: python ask.py "your question"
No LangGraph yet — this is the linear version, so you feel what RAG does before
we add orchestration.
"""
import os
import sys

from google import genai
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-005")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")

client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
db = firestore.Client(project=PROJECT)


def embed(text: str) -> list[float]:
    resp = client.models.embed_content(model=EMBED_MODEL, contents=text)
    return resp.embeddings[0].values


def retrieve(question: str, k: int = 3) -> list[dict]:
    """Find the k chunks whose embeddings are nearest the question's embedding."""
    qvec = embed(question)
    snaps = (
        db.collection("chunks")
        .find_nearest(
            vector_field="embedding",
            query_vector=Vector(qvec),
            distance_measure=DistanceMeasure.COSINE,
            limit=k,
        )
        .get()
    )
    return [s.to_dict() for s in snaps]


def answer(question: str) -> None:
    chunks = retrieve(question)
    context = "\n\n".join(
        f"[{c['doc_id']} #{c['chunk_index']}] {c['text']}" for c in chunks
    )
    prompt = (
        "Answer the question using ONLY the context below, and cite the [source #] "
        "you used. If the answer is not in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    resp = client.models.generate_content(model=MODEL, contents=prompt)

    print("retrieved chunks (nearest by meaning):")
    for c in chunks:
        print(f"  [{c['doc_id']} #{c['chunk_index']}] {c['text'][:70]}...")
    print("\nanswer:\n" + resp.text)


if __name__ == "__main__":
    answer(sys.argv[1])
