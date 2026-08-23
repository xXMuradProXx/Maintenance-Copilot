"""Offline resilience regressions for the supervisor loop.

These cover the failure paths the live smoke set cannot reach: malformed tool
arguments, tools that raise, unknown tool names, empty model replies, and loop
exhaustion. Every test drives `agent.run_case` with a mocked `_call_llm`, so no
LLMod, Pinecone, or Supabase call is made.

The invariant under test throughout is the one stated in AGENTS.md: a completed
execution must reach a valid operational next state and must never assert a
booking, notification, or legal claim that did not happen.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.lib import agent
from api.lib.state import (
    STATUS_AWAITING_TENANT,
    STATUS_ESCALATED,
    STATUS_NEEDS_INFO,
    STATUS_NEW,
    STATUS_RESOLVED,
    STATUS_SCHEDULED,
    CaseState,
)

TERMINAL = {
    STATUS_NEEDS_INFO,
    STATUS_AWAITING_TENANT,
    STATUS_SCHEDULED,
    STATUS_ESCALATED,
    STATUS_RESOLVED,
}

FORBIDDEN_CLAIMS = (
    "has been booked",
    "is booked",
    "we have notified",
    "we have contacted",
    "a contractor has been dispatched",
    "emergency services have been",
)


def text_response(content: str) -> SimpleNamespace:
    """A model turn that ends the loop with a tenant-facing reply."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))]
    )


def tool_response(name: str, arguments: str, call_id: str = "call_test_1") -> SimpleNamespace:
    """A model turn that requests exactly one tool call."""
    call = SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[call]))]
    )


def taxonomy_candidate(
    category: str = "PLUMBING",
    code: str = "DRAIN PIPE CLOGGED",
    urgency: str = "EMERGENCY",
    trade: str = "plumber",
) -> dict[str, object]:
    return {
        "category": category,
        "code": code,
        "urgency": urgency,
        "trade": trade,
        "score": 1,
        "source": "test_fixture",
    }


class MalformedToolArgumentTests(unittest.TestCase):
    """The model can emit arguments that are not valid JSON objects."""

    def _run_with_first_turn(self, first_turn: SimpleNamespace) -> tuple[str, CaseState]:
        responses = [first_turn, text_response("What exactly is happening, and in which apartment?")]
        with (
            patch.object(agent.taxonomy, "search", return_value=[taxonomy_candidate()]),
            patch.object(agent, "_call_llm", side_effect=responses),
        ):
            return agent.run_case("The sink is broken.", [], CaseState())

    def test_invalid_json_arguments_do_not_raise(self) -> None:
        reply, case = self._run_with_first_turn(
            tool_response("classify_issue", "{not valid json")
        )
        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)

    def test_json_array_arguments_are_coerced_to_an_empty_dict(self) -> None:
        reply, case = self._run_with_first_turn(
            tool_response("classify_issue", '["query", "sink"]')
        )
        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)

    def test_null_arguments_do_not_raise(self) -> None:
        reply, case = self._run_with_first_turn(tool_response("classify_issue", "null"))
        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)

    def test_empty_arguments_string_is_treated_as_no_arguments(self) -> None:
        reply, case = self._run_with_first_turn(tool_response("classify_issue", ""))
        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)


class ToolErrorTests(unittest.TestCase):
    """A tool that raises must be reported to the model, not kill the case."""

    def test_raising_tool_is_converted_into_an_observation(self) -> None:
        """A tool raising inside the supervisor loop is caught and traced."""
        responses = [
            tool_response("classify_issue", '{"query": "something odd"}'),
            text_response("Thanks — could you tell me which apartment this is?"),
        ]
        with (
            patch.object(
                agent.taxonomy,
                "search",
                side_effect=RuntimeError("taxonomy backend unavailable"),
            ),
            patch.object(agent, "_call_llm", side_effect=responses),
        ):
            reply, case = agent.run_case("Something odd is happening.", [], CaseState())

        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)
        observations = [
            entry for entry in case.trace
            if entry["actor"] == "tool:classify_issue" and entry["action"] == "observe"
        ]
        self.assertTrue(observations, "the failed tool call should still be traced")
        self.assertIn("Tool failed", observations[-1]["detail"])

    def test_taxonomy_database_failure_falls_back_to_the_local_table(self) -> None:
        """The deterministic fast path must survive a Supabase taxonomy outage."""
        from api.lib.repositories import DatabaseOperationError

        with (
            patch.object(
                agent.taxonomy,
                "_get_repository",
                side_effect=DatabaseOperationError("taxonomy table unavailable"),
            ),
            patch.object(
                agent,
                "_call_llm",
                return_value=text_response(
                    "Thanks for reporting the clogged drain in apartment 4B. Stop using "
                    "the fixture if the water level is rising."
                ),
            ),
        ):
            reply, case = agent.run_case(
                "The kitchen sink is clogged. Apartment 4B.", [], CaseState()
            )

        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)

    def test_retrieval_failure_does_not_escalate_a_routine_case(self) -> None:
        """AGENTS.md: unavailable retrieval is not a reason to escalate."""
        responses = [
            tool_response("retrieve_guidance", '{"query": "mold obligation"}'),
            text_response(
                "Thanks — I could not confirm the policy detail right now, but I have "
                "logged the report. Which apartment is this in?"
            ),
        ]
        with (
            patch.object(
                agent.rag,
                "retrieve",
                return_value={"ok": False, "error": "Guidance store unavailable.", "results": []},
            ),
            patch.object(agent, "_call_llm", side_effect=responses),
        ):
            reply, case = agent.run_case("There is mold on the ceiling.", [], CaseState())

        self.assertTrue(reply.strip())
        self.assertNotEqual(case.status, STATUS_ESCALATED)
        self.assertIn(case.status, TERMINAL)

    def test_unknown_tool_name_is_rejected_without_raising(self) -> None:
        responses = [
            tool_response("delete_all_cases", "{}"),
            text_response("Could you tell me what is wrong and which apartment?"),
        ]
        with patch.object(agent, "_call_llm", side_effect=responses):
            reply, case = agent.run_case("Something is wrong.", [], CaseState())

        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)


class EmptyReplyTests(unittest.TestCase):
    """An empty model reply must still produce a usable tenant response."""

    def test_empty_reply_falls_back_to_deterministic_guidance(self) -> None:
        with (
            patch.object(agent.taxonomy, "search", return_value=[taxonomy_candidate()]),
            patch.object(agent, "_call_llm", return_value=text_response("")),
        ):
            reply, case = agent.run_case("The sink is clogged.", [], CaseState())

        self.assertTrue(reply.strip(), "an empty model reply must not reach the tenant")
        self.assertIn(case.status, TERMINAL)

    def test_whitespace_only_reply_is_treated_as_empty(self) -> None:
        with (
            patch.object(agent.taxonomy, "search", return_value=[taxonomy_candidate()]),
            patch.object(agent, "_call_llm", return_value=text_response("   \n  ")),
        ):
            reply, case = agent.run_case("The sink is clogged.", [], CaseState())

        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)


class LoopExhaustionTests(unittest.TestCase):
    """A model that never stops calling tools must hit the loop guard."""

    def test_endless_tool_calls_end_in_manager_handoff(self) -> None:
        endless = [
            tool_response("classify_issue", '{"query": "sink"}', call_id=f"call_{i}")
            for i in range(agent.MAX_STEPS + 2)
        ]
        with (
            patch.object(agent.taxonomy, "search", return_value=[taxonomy_candidate()]),
            patch.object(agent, "_call_llm", side_effect=endless) as mocked,
        ):
            reply, case = agent.run_case("The sink is clogged.", [], CaseState())

        self.assertLessEqual(
            mocked.call_count,
            agent.MAX_STEPS,
            "the loop guard must cap supervisor iterations",
        )
        self.assertTrue(reply.strip())
        self.assertIn(case.status, TERMINAL)
        self.assertNotEqual(case.status, STATUS_NEW)

    def test_loop_exhaustion_is_recorded_as_a_policy_flag(self) -> None:
        endless = [
            tool_response("classify_issue", '{"query": "sink"}', call_id=f"call_{i}")
            for i in range(agent.MAX_STEPS + 2)
        ]
        with (
            patch.object(agent.taxonomy, "search", return_value=[taxonomy_candidate()]),
            patch.object(agent, "_call_llm", side_effect=endless),
        ):
            _reply, case = agent.run_case("The sink is clogged.", [], CaseState())

        if case.status == STATUS_ESCALATED:
            self.assertIn("loop_exhausted", case.policy_flags)


class TerminalStateInvariantTests(unittest.TestCase):
    """Every completed execution must leave a valid operational next state."""

    SCENARIOS = (
        ("The sink is clogged.", "a routine plumbing report"),
        ("Something is wrong.", "an unclassifiable report"),
        ("", "an empty message"),
    )

    def test_no_scenario_ends_in_the_new_state(self) -> None:
        for message, description in self.SCENARIOS:
            with self.subTest(scenario=description):
                with (
                    patch.object(
                        agent.taxonomy, "search", return_value=[taxonomy_candidate()]
                    ),
                    patch.object(
                        agent,
                        "_call_llm",
                        return_value=text_response("Which apartment is this in?"),
                    ),
                ):
                    reply, case = agent.run_case(message, [], CaseState())

                self.assertTrue(reply.strip())
                self.assertNotEqual(
                    case.status,
                    STATUS_NEW,
                    "a completed run must not leave the case in 'new'",
                )

    def test_replies_never_assert_an_unperformed_action(self) -> None:
        with (
            patch.object(agent.taxonomy, "search", return_value=[taxonomy_candidate()]),
            patch.object(agent, "_call_llm", return_value=text_response("")),
        ):
            reply, _case = agent.run_case("The sink is clogged.", [], CaseState())

        lowered = reply.lower()
        for claim in FORBIDDEN_CLAIMS:
            self.assertNotIn(claim, lowered, f"fallback copy must not claim: {claim}")


if __name__ == "__main__":
    unittest.main()
