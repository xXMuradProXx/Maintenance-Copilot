"""Deterministic, low-risk tenant guidance for common maintenance symptoms.

This is an operational response playbook, not legal guidance and not a repair
manual. It deliberately limits itself to reversible containment steps and
questions that change safety, urgency, or routing. Official obligations still
come only from the approved RAG corpus.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _toilet_clog_plan(message: str) -> Dict[str, Any]:
    questions: List[Dict[str, str]] = []

    if not _matches(
        r"\b(no|not|isn'?t|is not)\s+(overflowing|rising)\b|"
        r"\b(overflowing|overflow|rising|water at the rim)\b",
        message,
    ):
        questions.append(
            {
                "field": "overflow status",
                "question": "Is the bowl overflowing or is the water still rising?",
            }
        )

    if not _matches(
        r"\b(only|one)\s+(toilet|bathroom)\b|"
        r"\b(another|second|other)\s+(working\s+)?toilet\b|"
        r"\b(other toilet)\s+(works|is working|available)\b",
        message,
    ):
        questions.append(
            {
                "field": "other working toilet",
                "question": "Is there another working toilet in the apartment?",
            }
        )

    return {
        "key": "toilet_clog",
        "summary": "clogged toilet",
        "trade": "plumber",
        "safe_steps": [
            "Do not flush it again while the bowl is high.",
            "If the water starts rising and the shutoff valve behind the toilet is easy to reach, turn it clockwise without forcing it.",
            "Avoid chemical drain cleaners, which can create a splash hazard and complicate the repair.",
        ],
        "questions": questions[:2],
    }


def _drain_clog_plan(message: str) -> Dict[str, Any]:
    questions: List[Dict[str, str]] = []
    if not _matches(r"\b(other|multiple|all)\s+(drains|fixtures|sinks)\b|\bonly\s+(this|the)\s+(drain|sink)\b", message):
        questions.append(
            {
                "field": "affected fixtures",
                "question": "Is only this drain affected, or are other sinks or fixtures backing up too?",
            }
        )
    if not _matches(r"\b(no|not|isn'?t)\s+(overflowing|leaking)\b|\b(overflowing|leaking|standing water)\b", message):
        questions.append(
            {
                "field": "active overflow or leak",
                "question": "Is any water overflowing or leaking outside the fixture?",
            }
        )
    return {
        "key": "drain_clog",
        "summary": "clogged drain",
        "trade": "plumber",
        "safe_steps": [
            "Stop using the affected fixture if the water level is rising.",
            "Avoid chemical drain cleaners while the cause is unknown.",
        ],
        "questions": questions[:2],
    }


def _no_heat_plan(message: str) -> Dict[str, Any]:
    questions: List[Dict[str, str]] = []
    if not _matches(r"\b(all|entire|whole)\s+(apartment|unit)\b|\b(one|single)\s+(room|radiator)\b", message):
        questions.append(
            {
                "field": "heat extent",
                "question": "Is the whole apartment without heat, or only one room or radiator?",
            }
        )
    if not _matches(r"\b(child|baby|infant|elderly|disabled|pregnant|no vulnerable)\b", message):
        questions.append(
            {
                "field": "vulnerable occupants",
                "question": "Is anyone in the apartment especially vulnerable to cold?",
            }
        )
    return {
        "key": "no_heat",
        "summary": "no heat",
        "trade": "hvac",
        "safe_steps": [
            "Keep vents and radiators clear and close windows to retain heat.",
            "Do not use an oven or stovetop to heat the apartment.",
            "If you use a portable heater, use only an approved unit on a stable surface away from bedding, curtains, and other combustibles.",
        ],
        "questions": questions[:2],
    }


def _electrical_plan(message: str) -> Dict[str, Any]:
    hazardous = _matches(r"\b(spark|sparking|smoke|smoking|burning smell|hot outlet|exposed wire)\b", message)
    questions: List[Dict[str, str]] = []
    if not _matches(r"\b(one|single|only)\s+(outlet|socket|room)\b|\bwhole\s+(room|apartment|unit)\b", message):
        questions.append(
            {
                "field": "electrical extent",
                "question": "Is this limited to one outlet or fixture, or is power out in a larger area?",
            }
        )
    if not hazardous and not _matches(r"\b(no|not|without)\s+(sparks|smoke|burning smell|heat)\b", message):
        questions.append(
            {
                "field": "electrical hazard signs",
                "question": "Are there any sparks, smoke, unusual heat, or a burning smell?",
            }
        )
    steps = [
        "Stop using the affected outlet or fixture and unplug connected devices if they can be reached safely.",
        "Do not remove the cover or touch wiring.",
    ]
    if hazardous:
        steps.insert(0, "Keep everyone away from the affected area.")
    return {
        "key": "electrical_hazard" if hazardous else "electrical_failure",
        "summary": "electrical problem",
        "trade": "electrician",
        "safe_steps": steps,
        "questions": questions[:2],
    }


def _water_leak_plan(message: str) -> Dict[str, Any]:
    questions: List[Dict[str, str]] = []
    if not _matches(r"\b(ceiling|wall|sink|toilet|tub|shower|pipe|radiator|appliance)\b", message):
        questions.append(
            {
                "field": "leak source",
                "question": "Where is the water coming from?",
            }
        )
    if not _matches(r"\b(drip|dripping|pouring|gushing|stopped|not active|slow|fast)\b", message):
        questions.append(
            {
                "field": "leak rate",
                "question": "Is it a slow drip, or is water actively flowing?",
            }
        )
    return {
        "key": "water_leak",
        "summary": "water leak",
        "trade": "plumber",
        "safe_steps": [
            "Stop using the nearby fixture and move belongings away from the water.",
            "Use a container or towels to limit spread if it is safe to do so.",
            "If a nearby fixture shutoff is easy to reach, turn it clockwise without forcing it.",
            "Keep away from any wet electrical fixture or outlet.",
        ],
        "questions": questions[:2],
    }


def _lock_plan(message: str) -> Dict[str, Any]:
    questions: List[Dict[str, str]] = []
    if not _matches(r"\b(can|cannot|can't|cant|unable to)\s+(lock|secure)\b|\bwon'?t lock\b", message):
        questions.append(
            {
                "field": "security status",
                "question": "Can the apartment door currently be closed and secured?",
            }
        )
    return {
        "key": "entry_lock",
        "summary": "entry lock problem",
        "trade": "locksmith",
        "safe_steps": [
            "Do not force the key or dismantle the lock.",
            "If the apartment cannot be secured, stay in a safe place and say so in your reply so the repair can be prioritized.",
        ],
        "questions": questions[:2],
    }


def plan_for(message: str, case: Any) -> Dict[str, Any]:
    """Return safe steps and unresolved routing questions for the current case."""
    context = " ".join(
        value
        for value in (
            message or "",
            getattr(case, "summary", None) or "",
            getattr(case, "problem_code", None) or "",
        )
        if value
    )
    lowered = context.lower()

    if "toilet" in lowered and _matches(r"\b(clog|clogged|blocked|stopped up|won'?t flush)\b", lowered):
        return _toilet_clog_plan(message)
    if _matches(r"\b(sink|drain|shower|tub)\b", lowered) and _matches(
        r"\b(clog|clogged|blocked|slow drain|draining slowly|backed up)\b",
        lowered,
    ):
        return _drain_clog_plan(message)
    if _matches(r"\b(no heat|heat is off|heating (is )?(not working|broken|out)|radiator[^.]{0,20}cold)\b", lowered):
        return _no_heat_plan(message)
    if _matches(r"\b(outlet|socket|light fixture|electric|electrical|wire|wiring)\b", lowered) and _matches(
        r"\b(not working|dead|spark|sparking|smoke|smoking|burning smell|hot|exposed|power out)\b",
        lowered,
    ):
        return _electrical_plan(message)
    if _matches(r"\b(leak|leaking|dripping|water stain|wet wall|wet ceiling|burst pipe|flooding)\b", lowered):
        return _water_leak_plan(message)
    if _matches(r"\b(lock|deadbolt|key)\b", lowered) and _matches(
        r"\b(broken|stuck|won'?t lock|cannot lock|can't lock|locked out)\b",
        lowered,
    ):
        return _lock_plan(message)

    questions: List[Dict[str, str]] = []
    if not getattr(case, "unit", None):
        questions.append(
            {
                "field": "unit",
                "question": "What is the apartment or unit number?",
            }
        )
    if not getattr(case, "issue_category", None) or not getattr(case, "vendor_trade", None):
        questions.append(
            {
                "field": "problem details",
                "question": "What exactly is happening, and where in the apartment is it happening?",
            }
        )
    return {
        "key": "generic",
        "summary": getattr(case, "summary", None) or "maintenance issue",
        "trade": getattr(case, "vendor_trade", None),
        "safe_steps": [],
        "questions": questions[:2],
    }
