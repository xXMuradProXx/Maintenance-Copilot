"""Shared LLMod/OpenAI-compatible client configuration.

LLMod runs an OpenAI-compatible LiteLLM proxy. All model traffic in this
project must use this factory so chat and embeddings share the same provider,
credentials, timeout, and retry behavior.
"""

import os
from typing import Any, Dict

from openai import OpenAI


class LLMConfigurationError(RuntimeError):
    """Raised when the LLMod client cannot be configured safely."""


def _api_key() -> str:
    return (os.getenv("LLMOD_API_KEY") or "").strip()


def _base_url() -> str:
    return (os.getenv("LLMOD_BASE_URL") or "").strip().rstrip("/")


def is_llmod_configured() -> bool:
    return bool(_api_key() and _base_url())


def get_llmod_client() -> OpenAI:
    """Create an OpenAI SDK client that is pinned to the LLMod proxy."""
    api_key = _api_key()
    base_url = _base_url()
    if not api_key:
        raise LLMConfigurationError(
            "Set LLMOD_API_KEY to the shared LLMod API key."
        )
    if not base_url:
        raise LLMConfigurationError(
            "Set LLMOD_BASE_URL (for example, https://api.llmod.ai)."
        )
    if not base_url.lower().startswith(("https://", "http://")):
        raise LLMConfigurationError("LLMOD_BASE_URL must be an HTTP(S) URL.")

    try:
        timeout = max(5.0, min(float(os.getenv("LLMOD_TIMEOUT_SECONDS", "45")), 240.0))
        max_retries = max(0, min(int(os.getenv("LLMOD_MAX_RETRIES", "2")), 5))
    except ValueError as exc:
        raise LLMConfigurationError(
            "LLMOD_TIMEOUT_SECONDS and LLMOD_MAX_RETRIES must be numeric."
        ) from exc

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


def llmod_public_status() -> Dict[str, Any]:
    """Return health metadata that never contains credentials."""
    return {
        "provider": "llmod",
        "configured": is_llmod_configured(),
        "base_url_configured": bool(_base_url()),
        "api_key_present": bool(_api_key()),
        "chat_model": os.getenv("LLMOD_MODEL", "MB5R2CF-azure/gpt-5.4-mini"),
        "embedding_model": os.getenv(
            "EMBED_MODEL", "MB5R2CF-azure/text-embedding-3-small"
        ),
    }
