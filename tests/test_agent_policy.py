"""Offline policy regressions for useful routine handling and demo scheduling."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from api.lib import agent, tenant_guidance, vendors
from api.lib.state import (
    STATUS_AWAITING_TENANT,
    STATUS_ESCALATED,
    STATUS_SCHEDULED,
    CaseState,
)


def text_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))]
    )


def taxonomy_candidate(
    category: str,
    code: str,
    urgency: str,
    trade: str,
) -> dict[str, object]:
    return {
        "category": category,
        "code": code,
        "urgency": urgency,
        "trade": trade,
        "score": 1,
        "source": "test_fixture",
    }


class RoutineHandlingPolicyTests(unittest.TestCase):
    def test_toilet_clog_gets_steps_questions_and_simulated_slots(self) -> None:
        old_unhelpful_reply = (
            "Thanks for reporting this. I've flagged the clogged toilet in apartment "
            "3A for immediate manager review."
        )
        case = CaseState()
        with (
            patch.object(
                agent.taxonomy,
                "search",
                return_value=[taxonomy_candidate("PLUMBING", "BOWL STOPPED UP", "EMERGENCY", "plumber")],
            ),
            patch.object(agent, "_call_llm", return_value=text_response(old_unhelpful_reply)),
        ):
            reply, result = agent.run_case(
                "Apartment 3A. Toilet is clogged.",
                [],
                case,
            )

        lowered = reply.lower()
        self.assertEqual(result.unit, "3A")
        self.assertEqual(result.status, STATUS_AWAITING_TENANT)
        self.assertNotIn("manager review", lowered)
        self.assertIn("do not flush", lowered)
        self.assertIn("overflowing", lowered)
        self.assertIn("another working toilet", lowered)
        self.assertIn("simulated plumber windows", lowered)
        self.assertIn("option 1", lowered)
        self.assertIn("no calendar is reserved", lowered)
        self.assertEqual(len(result.offered_slots), 3)
        self.assertTrue(all(slot["source"] == "simulated_vendor_directory" for slot in result.offered_slots))

    def test_common_trades_get_containment_questions_and_slots_without_escalation(self) -> None:
        scenarios = (
            {
                "message": "Apartment 12C has no heat.",
                "candidate": taxonomy_candidate("HEATING", "NO HEAT", "EMERGENCY", "hvac"),
                "trade": "hvac",
                "terms": ("oven", "heater", "whole apartment"),
            },
            {
                "message": "The outlet is not working in apartment 5B.",
                "candidate": taxonomy_candidate("ELECTRIC", "OUTLET NOT WORKING", "ROUTINE", "electrician"),
                "trade": "electrician",
                "terms": ("unplug", "wiring", "sparks"),
            },
            {
                "message": "There is a leak in apartment 6D.",
                "candidate": taxonomy_candidate("PLUMBING", "WATER LEAK", "URGENT", "plumber"),
                "trade": "plumber",
                "terms": ("belongings", "electrical", "where is the water"),
            },
            {
                "message": "The entry door lock is broken in apartment 2A.",
                "candidate": taxonomy_candidate("DOOR/WINDOW", "ENTRY DOOR LOCK BROKEN", "URGENT", "locksmith"),
                "trade": "locksmith",
                "terms": ("force", "secured", "simulated locksmith windows"),
            },
        )
        for scenario in scenarios:
            with self.subTest(message=scenario["message"]):
                with (
                    patch.object(
                        agent.taxonomy,
                        "search",
                        return_value=[scenario["candidate"]],
                    ),
                    patch.object(
                        agent,
                        "_call_llm",
                        return_value=text_response("This needs immediate manager review."),
                    ),
                ):
                    reply, case = agent.run_case(
                        scenario["message"],
                        [],
                        CaseState(channel="portal"),
                    )
                    lowered = reply.lower()
                    self.assertEqual(case.status, STATUS_AWAITING_TENANT)
                    self.assertEqual(case.vendor_trade, scenario["trade"])
                    self.assertNotIn("manager review", lowered)
                    for term in scenario["terms"]:
                        self.assertIn(term, lowered)
                    self.assertEqual(len(case.offered_slots), 3)

    def test_toilet_guidance_avoids_risky_diy_instructions(self) -> None:
        plan = tenant_guidance.plan_for(
            "Apartment 3A. Toilet is clogged.",
            CaseState(unit="3A"),
        )
        rendered = " ".join(plan["safe_steps"]).lower()
        self.assertIn("do not flush", rendered)
        self.assertIn("avoid chemical drain cleaners", rendered)
        self.assertNotIn("remove the toilet", rendered)
        self.assertNotIn("dismantle", rendered)

    def test_taxonomy_emergency_priority_does_not_force_manager_escalation(self) -> None:
        case = CaseState()
        result = agent._dispatch_tool(
            "record_work_order",
            {
                "summary": "clogged toilet",
                "issue_category": "PLUMBING",
                "problem_code": "BOWL STOPPED UP",
                "urgency": "EMERGENCY",
                "taxonomy_urgency": "EMERGENCY",
                "vendor_trade": "plumber",
                "unit": "3A",
            },
            case,
            "Apartment 3A. Toilet is clogged.",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(case.taxonomy_urgency, "EMERGENCY")
        self.assertEqual(case.urgency, "URGENT")
        self.assertNotEqual(case.status, STATUS_ESCALATED)

    def test_unsupported_manager_escalation_is_blocked(self) -> None:
        case = CaseState(unit="3A", vendor_trade="plumber")
        result = agent._dispatch_tool(
            "escalate_to_manager",
            {"reason": "routine toilet clog"},
            case,
            "Apartment 3A. Toilet is clogged.",
        )
        self.assertFalse(result["ok"])
        self.assertIn("escalation blocked", result["error"].lower())
        self.assertNotEqual(case.status, STATUS_ESCALATED)

    def test_non_force_safety_flag_routes_urgently_without_manager_shortcut(self) -> None:
        case = CaseState(
            unit="12C",
            safety_flag=True,
            safety_reason="No heat reported",
            vendor_trade="hvac",
            urgency="URGENT",
        )
        escalation = agent._dispatch_tool(
            "escalate_to_manager",
            {"reason": "taxonomy says emergency"},
            case,
            "No heat in apartment 12C.",
        )
        self.assertFalse(escalation["ok"])
        slots = agent._dispatch_tool(
            "find_vendor_slots",
            {"trade": "hvac"},
            case,
        )
        self.assertTrue(slots["ok"])
        self.assertEqual(case.status, STATUS_AWAITING_TENANT)

    def test_allowed_manager_gate_is_enforced_from_tenant_text(self) -> None:
        flags = agent._detect_policy_flags(
            "This is still not fixed and I have contacted my lawyer."
        )
        self.assertIn("repeat_unresolved", flags)
        self.assertIn("legal_threat", flags)
        case = CaseState(policy_flags=flags)
        result = agent._dispatch_tool(
            "escalate_to_manager",
            {"reason": "legal threat and repeat unresolved repair"},
            case,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(case.status, STATUS_ESCALATED)


class SimulatedBookingPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = CaseState(unit="3A", vendor_trade="plumber")
        result = agent._dispatch_tool(
            "find_vendor_slots",
            {"trade": "plumber"},
            self.case,
        )
        self.assertTrue(result["ok"])

    def test_explicit_option_selection_records_demo_only(self) -> None:
        selected = self.case.offered_slots[0]
        result = agent._dispatch_tool(
            "book_appointment",
            {"slot_id": selected["slot_id"]},
            self.case,
            "Option 1 works for me.",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(self.case.status, STATUS_SCHEDULED)
        self.assertEqual(self.case.appointment["slot_id"], selected["slot_id"])
        self.assertIn("no calendar was reserved", result["note"].lower())
        self.assertIn("no contractor was contacted", result["note"].lower())

    def test_run_case_completes_second_turn_without_another_llm_call(self) -> None:
        selected = self.case.offered_slots[0]
        with patch.object(agent, "_call_llm") as llm_call:
            reply, result = agent.run_case(
                "Option 1 works for me.",
                [],
                self.case,
            )
        llm_call.assert_not_called()
        self.assertEqual(result.status, STATUS_SCHEDULED)
        self.assertEqual(result.appointment["slot_id"], selected["slot_id"])
        self.assertIn("demo option 1 is selected", reply.lower())
        self.assertIn("no calendar was reserved", reply.lower())

    def test_unselected_or_mismatched_slot_is_rejected(self) -> None:
        second = self.case.offered_slots[1]
        ambiguous = agent._dispatch_tool(
            "book_appointment",
            {"slot_id": second["slot_id"]},
            self.case,
            "Any time is fine.",
        )
        self.assertFalse(ambiguous["ok"])
        self.assertIsNone(self.case.appointment)

        mismatch = agent._dispatch_tool(
            "book_appointment",
            {"slot_id": second["slot_id"]},
            self.case,
            "Option 1 works for me.",
        )
        self.assertFalse(mismatch["ok"])
        self.assertIsNone(self.case.appointment)

    def test_slots_are_numbered_unique_and_explicitly_simulated(self) -> None:
        self.assertEqual(
            [slot["option"] for slot in self.case.offered_slots],
            [1, 2, 3],
        )
        self.assertEqual(len({slot["label"] for slot in self.case.offered_slots}), 3)
        self.assertTrue(all(slot["source"] == "simulated_vendor_directory" for slot in self.case.offered_slots))
        self.assertIsNone(
            vendors.resolve_explicit_selection(
                "The morning seems okay.",
                self.case.offered_slots,
            )
        )

    def test_every_demo_vendor_trade_has_three_generated_windows(self) -> None:
        trades = {vendor["trade"] for vendor in vendors.VENDORS}
        for trade in trades:
            with self.subTest(trade=trade):
                result = vendors.find_slots(trade)
                self.assertTrue(result["ok"])
                self.assertTrue(result["simulation"])
                self.assertEqual(len(result["slots"]), 3)

    def test_duplicate_retry_is_idempotent_and_different_option_is_blocked(self) -> None:
        first = self.case.offered_slots[0]
        initial = agent._dispatch_tool(
            "book_appointment",
            {"slot_id": first["slot_id"]},
            self.case,
            "Option 1 works.",
        )
        self.assertTrue(initial["ok"])
        duplicate = agent._dispatch_tool(
            "book_appointment",
            {"slot_id": first["slot_id"]},
            self.case,
            "Option 1 works.",
        )
        self.assertTrue(duplicate["ok"])
        self.assertTrue(duplicate["idempotent"])

        second = self.case.offered_slots[1]
        changed = agent._dispatch_tool(
            "book_appointment",
            {"slot_id": second["slot_id"]},
            self.case,
            "Option 2 works.",
        )
        self.assertFalse(changed["ok"])
        self.assertEqual(self.case.appointment["slot_id"], first["slot_id"])

    def test_expired_demo_slot_is_rejected(self) -> None:
        stale = dict(self.case.offered_slots[0])
        stale["date"] = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        stale["slot_id"] = "PL-01-STALE-10"
        self.case.offered_slots = [stale]
        result = agent._dispatch_tool(
            "book_appointment",
            {"slot_id": stale["slot_id"]},
            self.case,
            stale["slot_id"],
        )
        self.assertFalse(result["ok"])
        self.assertIn("expired", result["error"].lower())
        self.assertIsNone(self.case.appointment)


if __name__ == "__main__":
    unittest.main()
