"""Read-only verification for the Maintenance Copilot Supabase migration."""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
load_dotenv(ROOT / ".env")

from lib.supabase_client import (  # noqa: E402
    check_supabase_connection,
    get_supabase_client,
)


EXPECTED_TABLES = (
    "hpd_taxonomy",
    "cases",
    "messages",
    "case_events",
    "rag_documents",
    "rag_chunks",
    "vendors",
    "vendor_slots",
    "appointments",
)


def main() -> int:
    status = check_supabase_connection()
    if not status.get("configured"):
        print("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SECRET_KEY.")
        return 1
    if not status.get("migration_applied"):
        print(
            "Supabase credentials were found, but migration 001 could not be verified. "
            "Run supabase/migrations/001_initial_schema.sql in the Supabase SQL Editor."
        )
        return 1

    client = get_supabase_client()
    failures = []
    for table in EXPECTED_TABLES:
        try:
            client.table(table).select("*").limit(1).execute()
            print(f"[ok] {table}")
        except Exception:  # noqa: BLE001 - keep credentials/errors out of terminal output
            failures.append(table)
            print(f"[missing/unavailable] {table}")

    if failures:
        print("Migration verification failed for: " + ", ".join(failures))
        return 1

    print("Supabase migration 001 is installed and accessible.")
    if not status.get("taxonomy_has_rows"):
        print("The taxonomy table is empty, which is expected until the CSV loader step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
