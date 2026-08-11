"""Supabase repositories for durable agent state and structured data."""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from postgrest.types import CountMethod

from .supabase_client import get_supabase_client


class DatabaseOperationError(RuntimeError):
    """Raised when a repository operation cannot be completed."""


def _first(data: Any) -> Optional[Dict[str, Any]]:
    if isinstance(data, list):
        return data[0] if data else None
    return data if isinstance(data, dict) else None


class CaseRepository:
    """Create and update cases, messages, and ordered execution events."""

    _CASE_FIELDS = {
        "status", "channel", "unit", "summary", "issue_category",
        "problem_code", "urgency", "vendor_trade", "safety_flag",
        "safety_reason", "missing_info", "offered_slots", "appointment",
        "citations", "escalation_reason", "current_response", "metadata",
    }

    def __init__(self) -> None:
        self.client = get_supabase_client()

    @classmethod
    def _case_payload(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in values.items() if key in cls._CASE_FIELDS}

    def create_case(self, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = self._case_payload(values or {})
        try:
            response = self.client.table("cases").insert(payload).execute()
            case = _first(response.data)
            if not case:
                raise DatabaseOperationError("Supabase returned no created case.")
            return case
        except DatabaseOperationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not create the case in Supabase.") from exc

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = (
                self.client.table("cases")
                .select("*")
                .eq("id", case_id)
                .limit(1)
                .execute()
            )
            return _first(response.data)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not read the case from Supabase.") from exc

    def update_case(self, case_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._case_payload(values)
        if not payload:
            raise ValueError("No supported case fields were provided.")
        try:
            response = (
                self.client.table("cases")
                .update(payload)
                .eq("id", case_id)
                .execute()
            )
            case = _first(response.data)
            if not case:
                raise DatabaseOperationError(f"Case '{case_id}' was not found.")
            return case
        except DatabaseOperationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not update the case in Supabase.") from exc

    def append_message(self, case_id: str, role: str, content: str) -> Dict[str, Any]:
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"Unsupported message role '{role}'.")
        content = (content or "").strip()
        if not content:
            raise ValueError("Message content cannot be empty.")
        try:
            response = (
                self.client.table("messages")
                .insert({"case_id": case_id, "role": role, "content": content})
                .execute()
            )
            message = _first(response.data)
            if not message:
                raise DatabaseOperationError("Supabase returned no created message.")
            return message
        except DatabaseOperationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not append the message in Supabase.") from exc

    def append_event(
        self,
        case_id: str,
        module: str,
        event_type: str,
        *,
        prompt: Optional[Dict[str, Any]] = None,
        response: Any = None,
        detail: Optional[str] = None,
        model: Optional[str] = None,
        token_usage: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = {
            "p_case_id": case_id,
            "p_module": module,
            "p_event_type": event_type,
            "p_prompt": prompt,
            "p_response": response,
            "p_detail": detail,
            "p_model": model,
            "p_token_usage": token_usage,
        }
        try:
            result = self.client.rpc("append_case_event", params).execute()
            event = _first(result.data)
            if not event:
                raise DatabaseOperationError("Supabase returned no created case event.")
            return event
        except DatabaseOperationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not append the case event in Supabase.") from exc

    def list_messages(self, case_id: str) -> List[Dict[str, Any]]:
        try:
            response = (
                self.client.table("messages")
                .select("*")
                .eq("case_id", case_id)
                .order("created_at")
                .order("id")
                .execute()
            )
            return list(response.data or [])
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not list case messages.") from exc

    def list_events(self, case_id: str) -> List[Dict[str, Any]]:
        try:
            response = (
                self.client.table("case_events")
                .select("*")
                .eq("case_id", case_id)
                .order("step_number")
                .execute()
            )
            return list(response.data or [])
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not list case events.") from exc


class TaxonomyRepository:
    """Search and ingest the structured HPD taxonomy."""

    def __init__(self) -> None:
        self.client = get_supabase_client()

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        safe_top_k = max(1, min(int(top_k), 20))
        try:
            response = self.client.rpc(
                "search_hpd_taxonomy",
                {"query_text": query, "match_count": safe_top_k},
            ).execute()
            return list(response.data or [])
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not search the HPD taxonomy.") from exc

    def upsert_rows(
        self,
        rows: Iterable[Dict[str, Any]],
        *,
        batch_size: int = 200,
    ) -> int:
        batch_size = max(1, min(int(batch_size), 500))
        batch: List[Dict[str, Any]] = []
        written = 0

        def write_batch() -> None:
            nonlocal written
            if not batch:
                return
            self.client.table("hpd_taxonomy").upsert(
                batch,
                on_conflict="major_category,minor_category,problem_code,raw_type",
            ).execute()
            written += len(batch)
            batch.clear()

        try:
            for row in rows:
                batch.append(dict(row))
                if len(batch) >= batch_size:
                    write_batch()
            write_batch()
            return written
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not load HPD taxonomy rows.") from exc

    def count_rows(self) -> int:
        """Return the exact number of structured taxonomy rows."""
        try:
            response = (
                self.client.table("hpd_taxonomy")
                .select("id", count=CountMethod.exact, head=True)
                .execute()
            )
            return int(response.count or 0)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not count HPD taxonomy rows.") from exc


class RagRepository:
    """Maintain the Supabase manifest for Pinecone documents and chunks."""

    def __init__(self) -> None:
        self.client = get_supabase_client()

    def upsert_document(self, document: Dict[str, Any]) -> None:
        try:
            self.client.table("rag_documents").upsert(document).execute()
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not upsert the RAG document manifest.") from exc

    def upsert_chunks(
        self,
        chunks: Iterable[Dict[str, Any]],
        *,
        batch_size: int = 100,
    ) -> int:
        rows = list(chunks)
        batch_size = max(1, min(int(batch_size), 500))
        try:
            for start in range(0, len(rows), batch_size):
                self.client.table("rag_chunks").upsert(
                    rows[start:start + batch_size]
                ).execute()
            return len(rows)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not upsert RAG chunk manifests.") from exc

    def list_chunks(self, document_id: str) -> List[Dict[str, Any]]:
        try:
            response = (
                self.client.table("rag_chunks")
                .select(
                    "id,content_sha256,pinecone_namespace,page_start,page_end,section"
                )
                .eq("document_id", document_id)
                .execute()
            )
            return list(response.data or [])
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not list existing RAG chunks.") from exc

    def delete_chunks(self, chunk_ids: Iterable[str], *, batch_size: int = 100) -> int:
        ids = list(dict.fromkeys(str(value) for value in chunk_ids if value))
        batch_size = max(1, min(int(batch_size), 500))
        try:
            for start in range(0, len(ids), batch_size):
                self.client.table("rag_chunks").delete().in_(
                    "id", ids[start:start + batch_size]
                ).execute()
            return len(ids)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not remove stale RAG chunks.") from exc

    def mark_document_ingested(self, document_id: str) -> None:
        try:
            self.client.table("rag_documents").update(
                {"ingested_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", document_id).execute()
        except Exception as exc:  # noqa: BLE001
            raise DatabaseOperationError("Could not mark the RAG document as ingested.") from exc
