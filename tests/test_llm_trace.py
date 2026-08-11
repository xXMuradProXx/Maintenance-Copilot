"""Offline tests for exact, ordered LLM-call tracing."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api import index as _api_index  # noqa: F401 - initializes the local lib path
from lib import agent as agent_module
from lib.state import CaseState


def fake_response(content: str, total_tokens: int):
    message = SimpleNamespace(content=content, tool_calls=[])
    usage = SimpleNamespace(
        prompt_tokens=total_tokens - 2,
        completion_tokens=2,
        total_tokens=total_tokens,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=usage,
        model=agent_module.MODEL,
    )


class SequenceCompletions:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fake_client(responses):
    completions = SequenceCompletions(responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


class LlmTraceTests(unittest.TestCase):
    def test_each_successful_call_is_recorded_once_and_in_order(self) -> None:
        case = CaseState()
        messages = [
            {"role": "system", "content": "System instructions"},
            {"role": "user", "content": "Tenant message"},
        ]
        responses = [
            fake_response("first", 10),
            fake_response("second", 12),
        ]

        with patch.object(agent_module, "_get_client", return_value=fake_client(responses)):
            agent_module._call_llm(
                case,
                agent_module.SUPERVISOR_MODULE,
                messages,
            )
            agent_module._call_llm(
                case,
                agent_module.EMERGENCY_RESPONSE_MODULE,
                messages,
            )

        self.assertEqual(len(case.llm_steps), 2)
        self.assertEqual(
            [step["module"] for step in case.llm_steps],
            list(agent_module.LLM_MODULES),
        )
        self.assertEqual(
            [step["response"]["content"] for step in case.llm_steps],
            ["first", "second"],
        )
        for step in case.llm_steps:
            self.assertEqual(
                set(step["prompt"]),
                {"system_prompt", "user_prompt"},
            )

    def test_failed_call_is_recorded_exactly_once(self) -> None:
        case = CaseState()
        messages = [{"role": "user", "content": "Tenant message"}]
        client = fake_client([TimeoutError("provider timed out")])

        with (
            patch.object(agent_module, "_get_client", return_value=client),
            self.assertRaises(TimeoutError),
        ):
            agent_module._call_llm(
                case,
                agent_module.SUPERVISOR_MODULE,
                messages,
            )

        self.assertEqual(len(case.llm_steps), 1)
        step = case.llm_steps[0]
        self.assertEqual(step["module"], agent_module.SUPERVISOR_MODULE)
        self.assertIn("TimeoutError", step["response"]["error"])

    def test_unknown_llm_module_is_rejected_before_provider_call(self) -> None:
        case = CaseState()
        with self.assertRaisesRegex(ValueError, "Unknown LLM module"):
            agent_module._call_llm(
                case,
                "UnlistedAgent",
                [{"role": "user", "content": "Tenant message"}],
            )
        self.assertEqual(case.llm_steps, [])


if __name__ == "__main__":
    unittest.main()
