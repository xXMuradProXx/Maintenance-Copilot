"""Offline contract tests for the assignment-required HTTP API."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import index as api_index
from lib import agent as agent_module


ROOT = Path(__file__).resolve().parents[1]
EXECUTE_KEYS = {"status", "error", "response", "steps"}
STEP_KEYS = {"module", "prompt", "response"}
PROMPT_KEYS = {"system_prompt", "user_prompt"}


def make_step(module: str, sequence: int) -> dict[str, Any]:
    return {
        "module": module,
        "prompt": {
            "system_prompt": f"system prompt {sequence}",
            "user_prompt": f"user prompt {sequence}",
        },
        "response": {
            "model": agent_module.MODEL,
            "content": f"model response {sequence}",
            "tool_calls": [],
            "sequence": sequence,
        },
    }


class FakeCaseRepository:
    last_instance: "FakeCaseRepository | None" = None

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.events: list[dict[str, Any]] = []
        self.updated_values: dict[str, Any] | None = None
        type(self).last_instance = self

    def create_case(self, values: dict[str, Any]) -> dict[str, str]:
        return {"id": "database-case-id", "public_id": "MC-TEST01"}

    def append_message(self, case_id: str, role: str, content: str) -> None:
        self.messages.append((case_id, role, content))

    def update_case(self, case_id: str, values: dict[str, Any]) -> dict[str, Any]:
        self.updated_values = values
        return {"id": case_id, **values}

    def append_event(
        self,
        case_id: str,
        module: str,
        event_type: str,
        **values: Any,
    ) -> None:
        self.events.append(
            {
                "case_id": case_id,
                "module": module,
                "event_type": event_type,
                **values,
            }
        )


class FailingCaseRepository:
    def __init__(self) -> None:
        raise RuntimeError("database unavailable")


class AssignmentApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(api_index.app)

    def test_team_info_exact_contract_and_method(self) -> None:
        response = self.client.get("/api/team_info")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))

        body = response.json()
        self.assertEqual(
            set(body),
            {"group_batch_order_number", "team_name", "students"},
        )
        self.assertRegex(body["group_batch_order_number"], r"^\d+_\d+$")
        self.assertIsInstance(body["team_name"], str)
        self.assertGreaterEqual(len(body["students"]), 1)
        for student in body["students"]:
            self.assertEqual(set(student), {"name", "email"})
            self.assertIn("@", student["email"])

        self.assertEqual(self.client.post("/api/team_info").status_code, 405)

    def test_agent_info_required_contract_and_examples(self) -> None:
        response = self.client.get("/api/agent_info")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/json"))

        body = response.json()
        required_keys = {
            "description",
            "purpose",
            "prompt_template",
            "prompt_examples",
        }
        self.assertTrue(required_keys.issubset(body))
        self.assertIsInstance(body["description"], str)
        self.assertIsInstance(body["purpose"], str)
        self.assertIsInstance(body["prompt_template"], dict)
        self.assertIsInstance(body["prompt_template"]["template"], str)
        self.assertTrue(body["prompt_template"]["template"].strip())
        self.assertGreaterEqual(len(body["prompt_examples"]), 1)
        public_copy = json.dumps(body).lower()
        self.assertIn("simulated scheduling", public_copy)
        self.assertNotIn("has been alerted", public_copy)
        self.assertNotIn("contractor notified", public_copy)

        for example in body["prompt_examples"]:
            self.assertEqual(set(example), {"prompt", "full_response", "steps"})
            self.assertTrue(example["prompt"].strip())
            self.assertTrue(example["full_response"].strip())
            for step in example["steps"]:
                self.assert_step_contract(step)

        self.assertEqual(self.client.post("/api/agent_info").status_code, 405)

    def test_architecture_png_contract_and_dimensions(self) -> None:
        response = self.client.get("/api/model_architecture")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("image/png"))
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreaterEqual(len(response.content), 10_000)

        width, height = struct.unpack(">II", response.content[16:24])
        self.assertGreaterEqual(width, 1_000)
        self.assertGreaterEqual(height, 600)
        self.assertEqual(self.client.post("/api/model_architecture").status_code, 405)

    def test_execute_success_exact_contract_and_ordered_steps(self) -> None:
        expected_steps = [
            make_step(agent_module.SUPERVISOR_MODULE, 1),
            make_step(agent_module.SUPERVISOR_MODULE, 2),
            make_step(agent_module.EMERGENCY_RESPONSE_MODULE, 3),
        ]

        def fake_run_case(message: str, history: list[Any], case: Any):
            self.assertEqual(message, "The sink is clogged in apartment 4B.")
            self.assertEqual(history, [])
            case.llm_steps.extend(expected_steps)
            return "The request was recorded.", case

        with (
            patch.object(api_index, "is_llmod_configured", return_value=True),
            patch.object(api_index, "CaseRepository", FakeCaseRepository),
            patch.object(api_index, "run_case", side_effect=fake_run_case),
        ):
            response = self.client.post(
                "/api/execute",
                json={"prompt": "  The sink is clogged in apartment 4B.  "},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), EXECUTE_KEYS)
        self.assertEqual(body["status"], "ok")
        self.assertIsNone(body["error"])
        self.assertEqual(body["response"], "The request was recorded.")
        self.assertEqual(body["steps"], expected_steps)
        self.assertEqual(
            [step["response"]["sequence"] for step in body["steps"]],
            [1, 2, 3],
        )

        repository = FakeCaseRepository.last_instance
        self.assertIsNotNone(repository)
        assert repository is not None
        self.assertEqual(
            [event["response"]["sequence"] for event in repository.events],
            [1, 2, 3],
        )
        self.assertEqual(len(repository.events), len(expected_steps))
        self.assertEqual(self.client.get("/api/execute").status_code, 405)

    def test_execute_validation_failure_exact_contract(self) -> None:
        for payload in ({}, {"prompt": ""}, {"prompt": "   "}, {"prompt": 42}):
            with self.subTest(payload=payload):
                response = self.client.post("/api/execute", json=payload)
                self.assertEqual(response.status_code, 422)
                body = response.json()
                self.assertEqual(set(body), EXECUTE_KEYS)
                self.assertEqual(body["status"], "error")
                self.assertIsInstance(body["error"], str)
                self.assertTrue(body["error"].strip())
                self.assertIsNone(body["response"])
                self.assertEqual(body["steps"], [])

    def test_execute_provider_failure_exact_contract_and_trace(self) -> None:
        failure_step = make_step(agent_module.SUPERVISOR_MODULE, 1)
        failure_step["response"] = {
            "model": agent_module.MODEL,
            "error": "TimeoutError: provider timed out",
        }

        def failing_run_case(message: str, history: list[Any], case: Any):
            case.llm_steps.append(failure_step)
            raise TimeoutError("provider timed out")

        with (
            patch.object(api_index, "is_llmod_configured", return_value=True),
            patch.object(api_index, "CaseRepository", FakeCaseRepository),
            patch.object(api_index, "run_case", side_effect=failing_run_case),
        ):
            response = self.client.post(
                "/api/execute",
                json={"prompt": "The sink is clogged."},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), EXECUTE_KEYS)
        self.assertEqual(body["status"], "error")
        self.assertIn("TimeoutError", body["error"])
        self.assertIsNone(body["response"])
        self.assertEqual(body["steps"], [failure_step])

    def test_execute_database_failure_exact_contract(self) -> None:
        with (
            patch.object(api_index, "is_llmod_configured", return_value=True),
            patch.object(api_index, "CaseRepository", FailingCaseRepository),
        ):
            response = self.client.post(
                "/api/execute",
                json={"prompt": "The sink is clogged."},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), EXECUTE_KEYS)
        self.assertEqual(body["status"], "error")
        self.assertIn("RuntimeError", body["error"])
        self.assertIsNone(body["response"])
        self.assertEqual(body["steps"], [])

    def test_execute_unconfigured_provider_exact_contract(self) -> None:
        with patch.object(api_index, "is_llmod_configured", return_value=False):
            response = self.client.post(
                "/api/execute",
                json={"prompt": "The sink is clogged."},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), EXECUTE_KEYS)
        self.assertEqual(body["status"], "error")
        self.assertEqual(
            body["error"],
            "LLMod is not configured. Set LLMOD_BASE_URL and LLMOD_API_KEY.",
        )
        self.assertIsNone(body["response"])
        self.assertEqual(body["steps"], [])

    def test_public_module_names_match_architecture_and_examples(self) -> None:
        svg_path = Path(api_index._ARCHITECTURE_PNG).with_suffix(".svg")
        root = ET.parse(svg_path).getroot()
        diagram_text = {
            "".join(element.itertext()).strip()
            for element in root.iter()
            if element.tag.endswith("text")
        }

        response = self.client.get("/api/agent_info")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(tuple(body["modules"]), agent_module.PUBLIC_MODULES)
        self.assertTrue(set(agent_module.PUBLIC_MODULES).issubset(diagram_text))

        example_modules = {
            step["module"]
            for example in body["prompt_examples"]
            for step in example["steps"]
        }
        self.assertTrue(example_modules.issubset(set(agent_module.LLM_MODULES)))

        with self.assertRaises(ValueError):
            api_index.ExecutionStep.model_validate(
                make_step("UnlistedAgent", sequence=99)
            )

    def test_vercel_style_entrypoint_import_serves_architecture(self) -> None:
        code = (
            "from fastapi.testclient import TestClient; "
            "import index; "
            "response=TestClient(index.app).get('/api/model_architecture'); "
            "assert response.status_code == 200; "
            "assert response.headers['content-type'].startswith('image/png'); "
            "assert response.content.startswith(b'\\x89PNG\\r\\n\\x1a\\n')"
        )
        environment = os.environ.copy()
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT / "api",
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_agent_supports_direct_package_import(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import api.lib.agent"],
            cwd=ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def assert_step_contract(self, step: dict[str, Any]) -> None:
        self.assertEqual(set(step), STEP_KEYS)
        self.assertIn(step["module"], agent_module.LLM_MODULES)
        self.assertEqual(set(step["prompt"]), PROMPT_KEYS)
        self.assertIsInstance(step["prompt"]["system_prompt"], str)
        self.assertIsInstance(step["prompt"]["user_prompt"], str)
        self.assertIsInstance(step["response"], dict)


if __name__ == "__main__":
    unittest.main()
