"""Read-only smoke test for the agent-facing Supabase taxonomy search."""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
load_dotenv(ROOT / ".env")

from lib import taxonomy  # noqa: E402


CASES = (
    ("The kitchen sink is clogged and water drains very slowly. Apt 4B.", "PLUMBING", "DRAIN", "EMERGENCY"),
    ("The sink drain is overflowing with sewage.", "PLUMBING", "SEWAGE", "EMERGENCY"),
    ("No heat again since yesterday, apartment 12C", "HEAT", "NO HEAT", "EMERGENCY"),
    ("The wall is wet and smells bad", "PLUMBING", "DAMP OR WET", "ROUTINE"),
    ("The electric fixture sparks when I turn it on", "ELECTRIC", "SPARKS", "EMERGENCY"),
    # Intentionally vague: the supervisor should ask a follow-up question.
    ("bathroom problem", None, None, None),
)


def main() -> int:
    used_database = False
    failed = False
    for query, expected_category, expected_code, expected_urgency in CASES:
        matches = taxonomy.search(query, top_k=5)
        if any(match.get("source") == "supabase:hpd_taxonomy" for match in matches):
            used_database = True
        print("\nQUERY:", query)
        for index, match in enumerate(matches, start=1):
            print(
                f"  {index}. {match.get('category')} / {match.get('code')} | "
                f"{match.get('urgency')} | score={match.get('score')} | "
                f"count={match.get('complaint_count', '-')} | {match.get('source')}"
            )
        if expected_category:
            top = matches[0] if matches else {}
            passed = (
                expected_category in str(top.get("category", ""))
                and expected_code in str(top.get("code", ""))
                and top.get("urgency") == expected_urgency
            )
            print("  EXPECTATION:", "PASS" if passed else "FAIL")
            failed = failed or not passed

    if not used_database:
        print("\nFAILED: every query used the local outage fallback.")
        return 1
    if failed:
        print("\nFAILED: one or more live-search expectations did not match.")
        return 1
    print("\nAgent-facing taxonomy search reached Supabase.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
