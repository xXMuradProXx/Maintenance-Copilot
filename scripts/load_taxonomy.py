"""Validate and load the grouped HPD taxonomy CSV into Supabase.

The operation is idempotent: the migration's four-column source key is used
for upserts, so rerunning this script updates the same 641 rows.
"""

import argparse
import csv
import hashlib
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
CSV_PATH = ROOT / "data" / "Housing_Maintenance_Code_Complaints_and_Problems_grouped.csv"
EXPECTED_COLUMNS = {
    "Major Category",
    "Type",
    "Minor Category",
    "Problem Code",
    "Count",
}
EXPECTED_ROWS = 641
EXPECTED_TOTAL_COMPLAINTS = 11_586_134
URGENCY_MAP = {
    "IMMEDIATE EMERGENCY": "EMERGENCY",
    "EMERGENCY": "EMERGENCY",
    "HAZARDOUS": "URGENT",
    "NON EMERGENCY": "ROUTINE",
}

sys.path.insert(0, str(API_DIR))
load_dotenv(ROOT / ".env")

from lib.repositories import TaxonomyRepository  # noqa: E402


class TaxonomyValidationError(ValueError):
    """Raised when the approved grouped CSV does not match its contract."""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def load_and_validate(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise TaxonomyValidationError(f"CSV file not found: {path}")

    rows: List[Dict[str, Any]] = []
    source_keys = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        actual_columns = set(reader.fieldnames or [])
        if actual_columns != EXPECTED_COLUMNS:
            raise TaxonomyValidationError(
                f"Unexpected columns. Expected {sorted(EXPECTED_COLUMNS)}, "
                f"found {sorted(actual_columns)}."
            )

        for line_number, source in enumerate(reader, start=2):
            major_category = _clean(source["Major Category"]).upper()
            minor_category = _clean(source["Minor Category"]).upper()
            problem_code = _clean(source["Problem Code"]).upper()
            raw_type = _clean(source["Type"]).upper()
            count_text = _clean(source["Count"]).replace(",", "")

            if not major_category or not minor_category or not problem_code:
                raise TaxonomyValidationError(
                    f"Line {line_number} has a blank category or problem code."
                )
            if raw_type not in URGENCY_MAP:
                raise TaxonomyValidationError(
                    f"Line {line_number} has unsupported Type '{raw_type}'."
                )
            if not count_text.isdigit():
                raise TaxonomyValidationError(
                    f"Line {line_number} has invalid Count '{source['Count']}'."
                )

            source_key = (major_category, minor_category, problem_code, raw_type)
            if source_key in source_keys:
                raise TaxonomyValidationError(
                    f"Line {line_number} duplicates source key {source_key}."
                )
            source_keys.add(source_key)
            rows.append(
                {
                    "major_category": major_category,
                    "minor_category": minor_category,
                    "problem_code": problem_code,
                    "raw_type": raw_type,
                    "urgency": URGENCY_MAP[raw_type],
                    "complaint_count": int(count_text),
                }
            )

    if len(rows) != EXPECTED_ROWS:
        raise TaxonomyValidationError(
            f"Expected {EXPECTED_ROWS} rows, found {len(rows)}."
        )
    total_complaints = sum(row["complaint_count"] for row in rows)
    if total_complaints != EXPECTED_TOTAL_COMPLAINTS:
        raise TaxonomyValidationError(
            f"Expected {EXPECTED_TOTAL_COMPLAINTS:,} total complaints, "
            f"found {total_complaints:,}."
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing to Supabase.")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    try:
        rows = load_and_validate(CSV_PATH)
    except TaxonomyValidationError as exc:
        print(f"Validation failed: {exc}")
        return 1

    digest = hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()
    type_counts = Counter(row["raw_type"] for row in rows)
    print(f"Validated {len(rows)} taxonomy rows ({sum(row['complaint_count'] for row in rows):,} complaints).")
    print("Source SHA-256: " + digest)
    print("Types: " + ", ".join(f"{name}={count}" for name, count in sorted(type_counts.items())))

    if args.dry_run:
        print("Dry run complete; Supabase was not changed.")
        return 0

    repository = TaxonomyRepository()
    written = repository.upsert_rows(rows, batch_size=args.batch_size)
    stored = repository.count_rows()
    print(f"Upserted {written} rows; Supabase now contains {stored} taxonomy rows.")
    if stored != EXPECTED_ROWS:
        print(
            f"Verification failed: expected {EXPECTED_ROWS} stored rows, found {stored}. "
            "The loader does not delete unexpected pre-existing rows."
        )
        return 1

    probes = {
        "sink drain clogged": "PLUMBING",
        "fixture sparks when turned on": "ELECTRIC",
        "no heat": "HEAT",
    }
    for query, expected_category_fragment in probes.items():
        matches = repository.search(query, top_k=3)
        if not matches:
            print(f"Verification failed: no taxonomy matches for '{query}'.")
            return 1
        categories = {str(match.get("major_category", "")) for match in matches}
        if not any(expected_category_fragment in category for category in categories):
            print(
                f"Verification failed: '{query}' returned unexpected categories "
                f"{sorted(categories)}."
            )
            return 1
        top = matches[0]
        print(
            f"[search ok] {query!r} -> {top['major_category']} / "
            f"{top['problem_code']} ({top['urgency']})"
        )

    print("Taxonomy load and live-search verification complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

