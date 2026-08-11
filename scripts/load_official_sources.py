"""Extract official housing PDFs and optionally index them in Pinecone.

The default mode is a local-only dry run. Network calls and writes occur only
when ``--upload`` is supplied explicitly.
"""

import argparse
import hashlib
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
load_dotenv(ROOT / ".env")

from lib.llm_client import get_llmod_client  # noqa: E402
from lib.repositories import RagRepository  # noqa: E402


EMBED_DIMENSION = 1536
DEFAULT_NAMESPACE = "official-housing-v1"
TARGET_CHARS = 1_600
OVERLAP_CHARS = 220
MIN_PAGE_CHARS = 40


@dataclass(frozen=True)
class SourceSpec:
    id: str
    file_name: str
    title: str
    source_name: str
    source_type: str
    authority_rank: int
    expected_pages: int
    version: Optional[str] = None


@dataclass(frozen=True)
class ExtractedChunk:
    id: str
    document_id: str
    chunk_index: int
    page: int
    section: str
    text: str
    content_sha256: str


SOURCES = (
    SourceSpec(
        id="nyc-housing-maintenance-code",
        file_name="newyorkcity-ny-1.pdf",
        title="NYC Housing Maintenance Code (Title 27, Chapter 2)",
        source_name="New York City Administrative Code",
        source_type="law",
        authority_rank=10,
        expected_pages=76,
    ),
    SourceSpec(
        id="hpd-abcs-of-housing-2021",
        file_name="abcs-of-housing.pdf",
        title="ABCs of Housing",
        source_name="NYC Department of Housing Preservation and Development",
        source_type="official_guidance",
        authority_rank=20,
        expected_pages=35,
        version="2021",
    ),
    SourceSpec(
        id="hpd-repairs-maintenance-guidelines-1-02",
        file_name="hpd-guidelines-repairs-maintenance.pdf",
        title="HPD Guidelines for Repairs & Maintenance",
        source_name="NYC Department of Housing Preservation and Development",
        source_type="official_guidance",
        authority_rank=30,
        expected_pages=27,
        version="1.02 (draft 2023-01-01)",
    ),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clean_page_text(raw: str) -> str:
    """Normalize extracted text while retaining paragraph boundaries."""
    text = unicodedata.normalize("NFKC", raw or "")
    text = text.replace("\x00", "").replace("\u00ad", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)

    paragraphs: List[str] = []
    current: List[str] = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs).strip()


def _detect_section(raw: str, previous: str) -> str:
    """Find a useful page-level heading without inventing one."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in (raw or "").splitlines()]
    lines = [line for line in lines if 3 <= len(line) <= 160]

    for line in lines[:30]:
        match = re.match(r"^[§\u00a7]?\s*(27-\s?\d+(?:\.\d+)?)\s+(.+)$", line)
        if match:
            return f"§ {match.group(1).replace(' ', '')} {match.group(2)}"[:200]

    for line in lines[:20]:
        if re.match(r"^(?:[A-Z]|[IVX]+)\.\s+\S", line):
            return line[:200]
        letters = [char for char in line if char.isalpha()]
        if 5 <= len(letters) and len(line) <= 90:
            uppercase_ratio = sum(char.isupper() for char in letters) / len(letters)
            if uppercase_ratio >= 0.85:
                return line[:200]
    return previous


def _split_page(text: str) -> List[str]:
    """Split one page into bounded overlapping chunks."""
    if len(text) <= TARGET_CHARS:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(text):
        hard_end = min(start + TARGET_CHARS, len(text))
        end = hard_end
        if hard_end < len(text):
            boundary = max(
                text.rfind("\n\n", start + TARGET_CHARS // 2, hard_end),
                text.rfind(". ", start + TARGET_CHARS // 2, hard_end),
                text.rfind("; ", start + TARGET_CHARS // 2, hard_end),
            )
            if boundary > start:
                end = boundary + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        next_start = max(0, end - OVERLAP_CHARS)
        space = text.find(" ", next_start, min(end, next_start + 80))
        start = (space + 1) if space >= 0 else next_start
    return chunks


def extract_document(spec: SourceSpec) -> Dict[str, Any]:
    path = ROOT / "data" / spec.file_name
    if not path.is_file():
        raise ValueError(f"Required source PDF not found: {path}")

    file_bytes = path.read_bytes()
    reader = PdfReader(str(path), strict=False)
    if len(reader.pages) != spec.expected_pages:
        raise ValueError(
            f"{spec.file_name}: expected {spec.expected_pages} pages, "
            f"found {len(reader.pages)}. Review the source before indexing."
        )

    chunks: List[ExtractedChunk] = []
    skipped_pages: List[int] = []
    previous_section = spec.title
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text(extraction_mode="layout") or ""
        except TypeError:
            raw = page.extract_text() or ""
        section = _detect_section(raw, previous_section)
        previous_section = section or previous_section
        text = _clean_page_text(raw)
        if len(text) < MIN_PAGE_CHARS:
            skipped_pages.append(page_number)
            continue
        for page_chunk in _split_page(text):
            chunk_index = len(chunks)
            content_hash = _sha256_bytes(page_chunk.encode("utf-8"))
            chunks.append(
                ExtractedChunk(
                    id=f"{spec.id}:{chunk_index:05d}",
                    document_id=spec.id,
                    chunk_index=chunk_index,
                    page=page_number,
                    section=section or spec.title,
                    text=page_chunk,
                    content_sha256=content_hash,
                )
            )

    if not chunks:
        raise ValueError(f"{spec.file_name}: no usable text was extracted.")

    return {
        "spec": spec,
        "path": path,
        "content_sha256": _sha256_bytes(file_bytes),
        "page_count": len(reader.pages),
        "skipped_pages": skipped_pages,
        "chunks": chunks,
    }


def _document_manifest(document: Dict[str, Any]) -> Dict[str, Any]:
    spec: SourceSpec = document["spec"]
    return {
        "id": spec.id,
        "source_name": spec.source_name,
        "source_type": spec.source_type,
        "title": spec.title,
        "file_name": spec.file_name,
        "version": spec.version,
        "content_sha256": document["content_sha256"],
        "authority_rank": spec.authority_rank,
        "page_count": document["page_count"],
        "ingested_at": None,
        "metadata": {
            "skipped_pages": document["skipped_pages"],
            "chunking": {
                "target_chars": TARGET_CHARS,
                "overlap_chars": OVERLAP_CHARS,
                "page_bounded": True,
            },
        },
    }


def _chunk_manifest(chunk: ExtractedChunk, namespace: str) -> Dict[str, Any]:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "pinecone_namespace": namespace,
        "chunk_index": chunk.chunk_index,
        "page_start": chunk.page,
        "page_end": chunk.page,
        "section": chunk.section,
        "content_sha256": chunk.content_sha256,
        "text_content": chunk.text,
        "metadata": {"vector_id": chunk.id},
    }


def _vector_metadata(spec: SourceSpec, chunk: ExtractedChunk) -> Dict[str, Any]:
    return {
        "document_id": spec.id,
        "title": spec.title,
        "source_name": spec.source_name,
        "source_type": spec.source_type,
        "file_name": spec.file_name,
        "authority_rank": spec.authority_rank,
        "page_start": chunk.page,
        "page_end": chunk.page,
        "section": chunk.section,
        "content_sha256": chunk.content_sha256,
        "text": chunk.text,
    }


def validate_prepared_documents(documents: List[Dict[str, Any]], namespace: str) -> None:
    """Check local manifests and Pinecone metadata before any network call."""
    all_ids = set()
    hash_pattern = re.compile(r"^[0-9a-f]{64}$")
    for document in documents:
        spec: SourceSpec = document["spec"]
        manifest = _document_manifest(document)
        if not hash_pattern.fullmatch(manifest["content_sha256"]):
            raise ValueError(f"{spec.file_name}: invalid document SHA-256.")
        chunks: List[ExtractedChunk] = document["chunks"]
        if [chunk.chunk_index for chunk in chunks] != list(range(len(chunks))):
            raise ValueError(f"{spec.file_name}: chunk indexes are not contiguous.")
        for chunk in chunks:
            if chunk.id in all_ids:
                raise ValueError(f"Duplicate vector ID: {chunk.id}")
            all_ids.add(chunk.id)
            if not hash_pattern.fullmatch(chunk.content_sha256):
                raise ValueError(f"{chunk.id}: invalid content SHA-256.")
            if not (1 <= chunk.page <= document["page_count"]):
                raise ValueError(f"{chunk.id}: invalid page {chunk.page}.")
            if not chunk.text.strip() or len(chunk.text) > TARGET_CHARS + 5:
                raise ValueError(f"{chunk.id}: invalid chunk length {len(chunk.text)}.")
            chunk_manifest = _chunk_manifest(chunk, namespace)
            vector_metadata = _vector_metadata(spec, chunk)
            if chunk_manifest["text_content"] != vector_metadata["text"]:
                raise ValueError(f"{chunk.id}: manifest/vector text differs.")


def _index_names(client: Any) -> set[str]:
    indexes = client.list_indexes()
    if hasattr(indexes, "names"):
        return set(indexes.names())
    return {
        str(item.get("name") if isinstance(item, dict) else getattr(item, "name", ""))
        for item in indexes
    }


def _ensure_index(client: Any, index_name: str) -> Any:
    from pinecone import ServerlessSpec

    if index_name not in _index_names(client):
        client.create_index(
            name=index_name,
            dimension=EMBED_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=os.getenv("PINECONE_CLOUD", "aws"),
                region=os.getenv("PINECONE_REGION", "us-east-1"),
            ),
        )
        while not client.describe_index(index_name).status["ready"]:
            time.sleep(2)
    description = client.describe_index(index_name)
    dimension = int(
        description.get("dimension", 0)
        if isinstance(description, dict)
        else getattr(description, "dimension", 0)
    )
    if dimension != EMBED_DIMENSION:
        raise ValueError(
            f"Pinecone index '{index_name}' has dimension {dimension}; "
            f"expected {EMBED_DIMENSION}."
        )
    return client.Index(index_name)


def _batches(values: List[Any], size: int) -> Iterable[List[Any]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def upload_documents(
    documents: List[Dict[str, Any]],
    *,
    embed_batch_size: int,
    vector_batch_size: int,
    force: bool,
) -> None:
    from pinecone import Pinecone

    pinecone_key = (os.getenv("PINECONE_API_KEY") or "").strip()
    if not pinecone_key:
        raise ValueError("PINECONE_API_KEY is not configured.")

    index_name = os.getenv("PINECONE_INDEX", "maintenance-copilot")
    namespace = os.getenv("PINECONE_NAMESPACE", DEFAULT_NAMESPACE)
    embed_model = os.getenv(
        "EMBED_MODEL", "MB5R2CF-azure/text-embedding-3-small"
    )
    llmod = get_llmod_client()
    index = _ensure_index(Pinecone(api_key=pinecone_key), index_name)
    repository = RagRepository()

    for document in documents:
        spec: SourceSpec = document["spec"]
        chunks: List[ExtractedChunk] = document["chunks"]
        print(f"Uploading {spec.file_name}: {len(chunks)} chunks")
        existing_rows = {
            str(row["id"]): row for row in repository.list_chunks(spec.id)
        }
        existing_ids = set(existing_rows)
        repository.upsert_document(_document_manifest(document))

        changed_chunks = []
        for chunk in chunks:
            existing = existing_rows.get(chunk.id)
            unchanged = bool(
                existing
                and existing.get("content_sha256") == chunk.content_sha256
                and existing.get("pinecone_namespace") == namespace
                and existing.get("page_start") == chunk.page
                and existing.get("page_end") == chunk.page
                and (existing.get("section") or "") == chunk.section
            )
            if force or not unchanged:
                changed_chunks.append(chunk)

        pending_vectors: List[Dict[str, Any]] = []
        for chunk_batch in _batches(changed_chunks, embed_batch_size):
            response = llmod.embeddings.create(
                model=embed_model,
                input=[chunk.text for chunk in chunk_batch],
            )
            vectors = []
            for chunk, item in zip(chunk_batch, response.data):
                if len(item.embedding) != EMBED_DIMENSION:
                    raise ValueError(
                        f"Embedding for {chunk.id} has {len(item.embedding)} dimensions; "
                        f"expected {EMBED_DIMENSION}."
                    )
                vectors.append(
                    {
                        "id": chunk.id,
                        "values": item.embedding,
                        "metadata": _vector_metadata(spec, chunk),
                    }
                )
            pending_vectors.extend(vectors)
            while len(pending_vectors) >= vector_batch_size:
                index.upsert(
                    vectors=pending_vectors[:vector_batch_size],
                    namespace=namespace,
                )
                del pending_vectors[:vector_batch_size]
        if pending_vectors:
            index.upsert(vectors=pending_vectors, namespace=namespace)

        if changed_chunks:
            repository.upsert_chunks(
                [_chunk_manifest(chunk, namespace) for chunk in changed_chunks],
                batch_size=200,
            )
        current_ids = {chunk.id for chunk in chunks}
        stale_ids = sorted(existing_ids - current_ids)
        if stale_ids:
            for stale_batch in _batches(stale_ids, vector_batch_size):
                index.delete(ids=stale_batch, namespace=namespace)
            repository.delete_chunks(stale_ids)
        repository.mark_document_ingested(spec.id)
        print(
            f"  [ok] {spec.id}; embedded {len(changed_chunks)}, "
            f"reused {len(chunks) - len(changed_chunks)}, "
            f"removed {len(stale_ids)} stale chunks"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and validate locally without network calls (the default).",
    )
    mode.add_argument(
        "--upload",
        action="store_true",
        help="Embed through LLMod and write to Pinecone and Supabase.",
    )
    parser.add_argument(
        "--document",
        action="append",
        choices=[spec.id for spec in SOURCES],
        help="Process only this document ID; repeat to select multiple.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed every selected chunk even when its manifest is unchanged.",
    )
    parser.add_argument("--embed-batch-size", type=int, default=64)
    parser.add_argument("--vector-batch-size", type=int, default=200)
    args = parser.parse_args()

    selected = set(args.document or [])
    specs = [spec for spec in SOURCES if not selected or spec.id in selected]
    try:
        documents = [extract_document(spec) for spec in specs]
        namespace = os.getenv("PINECONE_NAMESPACE", DEFAULT_NAMESPACE)
        validate_prepared_documents(documents, namespace)
        total_chunks = 0
        for document in documents:
            spec: SourceSpec = document["spec"]
            chunks: List[ExtractedChunk] = document["chunks"]
            total_chunks += len(chunks)
            page_lengths: Dict[int, int] = {}
            for chunk in chunks:
                page_lengths[chunk.page] = page_lengths.get(chunk.page, 0) + len(chunk.text)
            print(
                f"[ok] {spec.file_name}: {document['page_count']} pages, "
                f"{len(chunks)} chunks, {sum(page_lengths.values()):,} chunk characters, "
                f"{len(document['skipped_pages'])} pages skipped"
            )
            print(f"     SHA-256 {document['content_sha256']}")
        print(f"Prepared {len(documents)} official documents and {total_chunks} chunks.")

        if not args.upload:
            if args.force:
                print("Note: --force has no effect without --upload.")
            print("Dry run complete. No LLMod, Pinecone, or Supabase calls were made.")
            return 0

        upload_documents(
            documents,
            embed_batch_size=max(1, min(args.embed_batch_size, 64)),
            vector_batch_size=max(1, min(args.vector_batch_size, 200)),
            force=args.force,
        )
        print("Official-source ingestion complete.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
