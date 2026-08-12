"""Offline regression checks for the public assignment UI."""

from __future__ import annotations

import unittest
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from api import index as api_index


class UiParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.textareas: list[dict[str, str | None]] = []
        self.buttons: list[tuple[dict[str, str | None], str]] = []
        self._button_attrs: dict[str, str | None] | None = None
        self._button_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.ids.add(element_id)
        if tag == "textarea":
            self.textareas.append(attributes)
        if tag == "button":
            self._button_attrs = attributes
            self._button_text = []

    def handle_data(self, data: str) -> None:
        if self._button_attrs is not None:
            self._button_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._button_attrs is not None:
            self.buttons.append(
                (self._button_attrs, " ".join("".join(self._button_text).split()))
            )
            self._button_attrs = None
            self._button_text = []


class PublicUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        response = TestClient(api_index.app).get("/")
        cls.response = response
        cls.html = response.text
        cls.parser = UiParser()
        cls.parser.feed(cls.html)

    def test_root_immediately_serves_the_required_agent_controls(self) -> None:
        self.assertEqual(self.response.status_code, 200)
        self.assertTrue(self.response.headers["content-type"].startswith("text/html"))
        self.assertEqual(len(self.parser.textareas), 1)
        textarea = self.parser.textareas[0]
        self.assertEqual(textarea.get("id"), "prompt")
        self.assertEqual(textarea.get("maxlength"), "4000")
        self.assertTrue(textarea.get("placeholder"))
        self.assertIn(
            "Run Agent",
            {button_text for _, button_text in self.parser.buttons},
        )
        self.assertNotIn("type=\"password\"", self.html)
        self.assertNotIn("Sign in", self.html)

    def test_execute_request_and_primary_response_regions_are_present(self) -> None:
        self.assertIn('const API_URL = "/api/execute"', self.html)
        self.assertIn("body: JSON.stringify({ prompt })", self.html)
        self.assertTrue(
            {
                "result-card",
                "result-title",
                "result-body",
                "trace-shell",
                "trace-list",
            }.issubset(self.parser.ids)
        )
        self.assertIn("Recommended next step", self.html)
        self.assertIn("Agent response", self.html)

    def test_trace_is_structured_complete_and_secondary(self) -> None:
        self.assertIn("<details class=\"card trace-shell\"", self.html)
        self.assertIn("Every LLM prompt and response, in chronological order", self.html)
        for label in (
            "System prompt",
            "User prompt",
            "Model response",
            "Tool calls",
            "Token usage",
            "Latency",
            "Error",
            "Complete response JSON",
        ):
            self.assertIn(label, self.html)
        self.assertIn("navigator.clipboard.writeText", self.html)
        self.assertIn("overflow-wrap: anywhere", self.html)

    def test_dead_ticket_path_and_external_fonts_are_removed(self) -> None:
        for removed_text in (
            "renderTicket",
            "caseState",
            "statusPill",
            "fonts.googleapis.com",
            "innerHTML",
        ):
            self.assertNotIn(removed_text, self.html)

    def test_loading_validation_retry_and_accessibility_states_exist(self) -> None:
        for expected in (
            "REQUEST_TIMEOUT_MS",
            "Retry request",
            "language-model service is not available",
            "case-record service is not available",
            "aria-live=\"polite\"",
            "aria-atomic=\"true\"",
            "aria-invalid",
            "prefers-reduced-motion",
            "focus-visible",
            "Ctrl",
            "Enter",
        ):
            self.assertIn(expected, self.html)

    def test_examples_cover_distinct_triage_scenarios(self) -> None:
        for tone in ("normal", "ambiguous", "urgent", "emergency"):
            self.assertIn(f'data-tone="{tone}"', self.html)
        self.assertIn("One-shot triage", self.html)
        self.assertIn("does not preserve follow-up conversations", self.html)
        self.assertIn("notify a manager or contractor", self.html)


if __name__ == "__main__":
    unittest.main()
