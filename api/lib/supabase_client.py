"""Lazy, backend-only Supabase client for Maintenance Copilot.

The secret key must remain in the Python/Vercel environment. This module is
never imported by the browser and never includes credentials in status output.
"""

import os
from functools import lru_cache
from typing import Any, Dict

from supabase import Client, create_client
from supabase.client import ClientOptions


class SupabaseConfigurationError(RuntimeError):
    """Raised when the backend Supabase environment is incomplete."""


def supabase_configured() -> bool:
    """Return whether both required backend environment variables are set."""
    return bool(
        os.getenv("SUPABASE_URL", "").strip()
        and os.getenv("SUPABASE_SECRET_KEY", "").strip()
    )


def _supabase_settings() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()

    missing = []
    if not url:
        missing.append("SUPABASE_URL")
    if not secret_key:
        missing.append("SUPABASE_SECRET_KEY")
    if missing:
        raise SupabaseConfigurationError(
            "Missing required Supabase environment variable(s): "
            + ", ".join(missing)
        )

    if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise SupabaseConfigurationError(
            "SUPABASE_URL must be an HTTPS URL (or a local Supabase URL)."
        )
    return url, secret_key


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Create one synchronous client per warm serverless process."""
    url, secret_key = _supabase_settings()
    options = ClientOptions(
        schema="public",
        auto_refresh_token=False,
        persist_session=False,
        postgrest_client_timeout=8,
        function_client_timeout=8,
        storage_client_timeout=8,
    )
    return create_client(url, secret_key, options=options)


def clear_supabase_client_cache() -> None:
    """Test helper for reloading changed environment configuration."""
    get_supabase_client.cache_clear()


def check_supabase_connection() -> Dict[str, Any]:
    """Return public-safe status and verify that migration 001 was applied."""
    if not supabase_configured():
        return {
            "configured": False,
            "connected": False,
            "migration_applied": False,
        }

    try:
        response = (
            get_supabase_client()
            .table("hpd_taxonomy")
            .select("id")
            .limit(1)
            .execute()
        )
        return {
            "configured": True,
            "connected": True,
            "migration_applied": True,
            "taxonomy_has_rows": bool(response.data),
        }
    except Exception:  # noqa: BLE001 - health output must remain public-safe
        return {
            "configured": True,
            "connected": False,
            "migration_applied": False,
        }

