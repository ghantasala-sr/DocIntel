"""Ingest a text document into Firestore as embedded chunks.

Usage: python ingest.py <path-to-.txt>
Splits the file into overlapping chunks, embeds each with Vertex AI, and stores
them (text + vector) in the Firestore `chunks` collection for later retrieval.
"""
import os
import sys

from google import genai
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector

PROJECT = os.environ.get("PROJECT_ID", "docintel-srg-2026")
LOCATION = os.environ.get("REGION", "us-central1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-005")

client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
db = firestore.Client(project=PROJECT)


def chunk_text(text: str, size: int = 600, overlap: int = 100) -> list[str]:
    """Split text into ~size-character windows that overlap by `overlap` chars.

    Overlap keeps a sentence that straddles a boundary retrievable from either side.
    Real systems use smarter, sentence-aware splitters; this is the simple version.
    """
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return [c.strip() for c in chunks if c.strip()]


def embed(text: str) -> list[float]:
    """Turn text into an embedding vector via Vertex AI."""
    resp = client.models.embed_content(model=EMBED_MODEL, contents=text)
    return resp.embeddings[0].values


def main(path: str) -> None:
    doc_id = os.path.basename(path)
    text = open(path, encoding="utf-8").read()
    chunks = chunk_text(text)
    print(f"{doc_id}: {len(chunks)} chunks")

    for i, chunk in enumerate(chunks):
        vector = embed(chunk)
        db.collection("chunks").add(
            {
                "doc_id": doc_id,
                "chunk_index": i,
                "text": chunk,
                "embedding": Vector(vector),
            }
        )
        print(f"  chunk {i}: stored ({len(vector)} dims)")
    print("done")


if __name__ == "__main__":
    main(sys.argv[1])
