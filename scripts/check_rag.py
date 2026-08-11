"""Live acceptance check for the official-source Pinecone corpus."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
load_dotenv(ROOT / ".env")

from lib import rag  # noqa: E402


CASES = (
    ("What temperatures are required during New York City heat season?", "Housing"),
    ("How does the housing code classify visible mold by square footage?", "Housing"),
    ("How long does an owner have to correct Class A, B, and C violations?", "Housing"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Required because this makes LLMod embedding and Pinecone query calls.",
    )
    args = parser.parse_args()
    if not args.live:
        print("No calls made. Re-run with --live after uploading the official corpus.")
        return 0

    failed = False
    for query, expected_title_fragment in CASES:
        result = rag.retrieve(query, top_k=4)
        print("\nQUERY:", query)
        if not result.get("ok"):
            print("  FAILED:", result.get("error"))
            failed = True
            continue
        for match in result["results"]:
            print(
                f"  {match['score']}: {match['title']} | page {match['page']} | "
                f"{match['section']}"
            )
        top_titles = " ".join(match["title"] for match in result["results"])
        if expected_title_fragment.lower() not in top_titles.lower():
            print("  FAILED: expected an official housing source in the results.")
            failed = True
        if any(not match.get("page") or not match.get("file_name") for match in result["results"]):
            print("  FAILED: one or more results lack page/file provenance.")
            failed = True

    if failed:
        return 1
    print("\nOfficial-source RAG retrieval passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
