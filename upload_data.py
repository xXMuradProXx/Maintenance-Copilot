"""One-time ingestion pipeline: data/housing_guidance/*.md -> Pinecone.

Mirrors the reference repo's upload_data.py: resilient batching with
progressive backoff on both the embedding and upsert calls.

Run locally (never on Vercel):
    python upload_data.py
"""

import glob
import os
import re
import sys
import time
from typing import Dict, List

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

# ------------------------------------------------------------------- settings

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "housing_guidance")
INDEX_NAME = os.getenv("PINECONE_INDEX", "maintenance-copilot")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = 1536                # dimension of text-embedding-3-small
CHUNK_SIZE = 900                # characters per chunk
CHUNK_OVERLAP = 150
EMBED_BATCH = 32
UPSERT_BATCH = 50
MAX_RETRIES = 5


# ------------------------------------------------------------------- chunking

def load_documents() -> List[Dict[str, str]]:
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "*.md")))
    if not paths:
        sys.exit(f"No .md files found in {DATA_DIR}")
    docs = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
        first_line = text.splitlines()[0] if text else ""
        title = first_line.lstrip("# ").strip() or os.path.basename(path)
        docs.append({"title": title, "source": os.path.basename(path), "text": text})
    return docs


def chunk_text(text: str) -> List[str]:
    """Paragraph-aware sliding-window chunker (~CHUNK_SIZE chars, with overlap)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= CHUNK_SIZE:
            current = f"{current}\n\n{para}".strip()
            continue
        if current:
            chunks.append(current)
            current = current[-CHUNK_OVERLAP:]  # keep a tail for context overlap
        while len(para) > CHUNK_SIZE:           # split oversized paragraphs
            chunks.append((current + "\n\n" + para[:CHUNK_SIZE]).strip())
            para = para[CHUNK_SIZE - CHUNK_OVERLAP:]
            current = ""
        current = f"{current}\n\n{para}".strip()
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------- resilient wrappers

def with_backoff(label: str, fn):
    """Call fn() with progressive backoff: 2s, 4s, 8s, 16s, 32s."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt
            print(f"  [{label}] attempt {attempt} failed ({type(exc).__name__}: {exc}); "
                  f"retrying in {wait}s...")
            time.sleep(wait)


# ----------------------------------------------------------------------- main

def main() -> None:
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("PINECONE_API_KEY"):
        sys.exit("Set OPENAI_API_KEY and PINECONE_API_KEY in your .env first.")

    openai_client = OpenAI()
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])

    # 1. Create the index if it doesn't exist yet.
    existing = {idx["name"] for idx in pc.list_indexes()}
    if INDEX_NAME not in existing:
        print(f"Creating Pinecone index '{INDEX_NAME}' ({EMBED_DIM} dims, cosine)...")
        pc.create_index(
            name=INDEX_NAME,
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        while not pc.describe_index(INDEX_NAME).status["ready"]:
            time.sleep(2)
        print("Index ready.")
    index = pc.Index(INDEX_NAME)

    # 2. Load + chunk the corpus.
    docs = load_documents()
    records = []
    for doc in docs:
        for i, chunk in enumerate(chunk_text(doc["text"])):
            records.append(
                {
                    "id": f"{doc['source']}::{i}",
                    "text": chunk,
                    "metadata": {"title": doc["title"], "source": doc["source"], "text": chunk},
                }
            )
    print(f"Loaded {len(docs)} documents -> {len(records)} chunks.")

    # 3. Embed in batches (progressive backoff).
    vectors = []
    for start in range(0, len(records), EMBED_BATCH):
        batch = records[start:start + EMBED_BATCH]
        response = with_backoff(
            "embed",
            lambda b=batch: openai_client.embeddings.create(
                model=EMBED_MODEL, input=[r["text"] for r in b]
            ),
        )
        for record, item in zip(batch, response.data):
            vectors.append(
                {"id": record["id"], "values": item.embedding, "metadata": record["metadata"]}
            )
        print(f"Embedded {min(start + EMBED_BATCH, len(records))}/{len(records)} chunks.")

    # 4. Upsert in batches (progressive backoff).
    for start in range(0, len(vectors), UPSERT_BATCH):
        batch = vectors[start:start + UPSERT_BATCH]
        with_backoff("upsert", lambda b=batch: index.upsert(vectors=b))
        print(f"Upserted {min(start + UPSERT_BATCH, len(vectors))}/{len(vectors)} vectors.")

    print(f"\nDone. Index '{INDEX_NAME}' now serves the RAG guidance corpus.")


if __name__ == "__main__":
    main()
