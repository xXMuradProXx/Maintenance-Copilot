"""Live smoke test proving the LLMod supervisor selects and executes tools."""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
load_dotenv(ROOT / ".env")

from lib.agent import run_case  # noqa: E402
from lib.state import CaseState  # noqa: E402


def main() -> int:
    message = "The kitchen sink is clogged and drains very slowly. Apartment 4B."
    reply, case = run_case(message, [], CaseState(channel="portal"))

    tool_modules = [
        str(step.get("actor"))
        for step in case.trace
        if str(step.get("actor", "")).startswith("tool:")
    ]
    print("status:", case.status)
    print("classification:", case.issue_category, "/", case.problem_code)
    print("urgency:", case.urgency)
    print("vendor trade:", case.vendor_trade)
    print("tool calls:", ", ".join(tool_modules) or "none")
    print("reply:", reply)

    required_tools = {"tool:classify_issue", "tool:record_work_order"}
    missing = required_tools - set(tool_modules)
    if missing:
        print("FAILED: supervisor did not call " + ", ".join(sorted(missing)))
        return 1
    if not reply.strip():
        print("FAILED: supervisor returned an empty tenant reply.")
        return 1
    if not case.issue_category or not case.problem_code or not case.urgency:
        print("FAILED: supervisor did not produce a structured work order.")
        return 1

    print("LLMod supervisor loop executed tools and produced a work order.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
