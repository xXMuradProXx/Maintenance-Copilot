"""Retrieval layer (RAG sub-agent tool).

Embeds the query with OpenAI and searches the Pinecone index built by
`upload_data.py` (housing code + HPD-style guidance corpus).

Degrades gracefully: if Pinecone is unreachable / not configured / empty, the
tool reports that instead of crashing, and the supervisor falls back to the
structured taxonomy + explicit policy in its prompt.
"""

import os
from typing import Any, Dict, List

from openai import OpenAI

EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")  # 1536 dims
INDEX_NAME = os.getenv("PINECONE_INDEX", "maintenance-copilot")

_openai_client = None
_pinecone_index = None


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()  # reads OPENAI_API_KEY
    return _openai_client


def _get_index():
    global _pinecone_index
    if _pinecone_index is None:
        from pinecone import Pinecone  # imported lazily to speed cold starts

        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise RuntimeError("PINECONE_API_KEY is not set")
        _pinecone_index = Pinecone(api_key=api_key).Index(INDEX_NAME)
    return _pinecone_index


def _match_field(match: Any, field: str, default: Any = None) -> Any:
    """Pinecone SDK versions differ between dict-like and attribute access."""
    if isinstance(match, dict):
        return match.get(field, default)
    return getattr(match, field, default)


def retrieve(query: str, top_k: int = 4) -> Dict[str, Any]:
    """Semantic search over the guidance corpus. Never raises."""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "Empty retrieval query.", "results": []}

    try:
        embedding = (
            _get_openai()
            .embeddings.create(model=EMBED_MODEL, input=[query])
            .data[0]
            .embedding
        )
        response = _get_index().query(
            vector=embedding, top_k=top_k, include_metadata=True
        )
        matches = _match_field(response, "matches", []) or []

        results: List[Dict[str, str]] = []
        for m in matches:
            metadata = _match_field(m, "metadata", {}) or {}
            results.append(
                {
                    "title": str(metadata.get("title", "untitled")),
                    "text": str(metadata.get("text", ""))[:700],
                    "score": round(float(_match_field(m, "score", 0.0)), 3),
                }
            )
        if not results:
            return {
                "ok": False,
                "error": "No guidance found for this query (index may be empty — "
                         "run upload_data.py).",
                "results": [],
            }
        return {"ok": True, "results": results}

    except Exception as exc:  # noqa: BLE001 — tool must never crash the agent
        return {
            "ok": False,
            "error": f"Guidance store unavailable ({type(exc).__name__}). "
                     "Proceed using the taxonomy and the explicit policy rules.",
            "results": [],
        }
