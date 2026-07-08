"""Safety Pre-Filter.

Deterministic, rule-based check that runs BEFORE the LLM supervisor sees the
message (architecture slide: "Rule-based emergency flag -> can force-escalate").

Two tiers:
  * FORCE rules  -> life-safety events. The case is escalated immediately and
    the supervisor loop is bypassed; the tenant gets canned safety guidance
    (optionally polished by one LLM call, with a hard-coded fallback).
  * FLAG rules   -> hazardous but not bypass-worthy. The supervisor still runs,
    but is told to treat the case as an emergency unless clearly contradicted.
"""

import re
from typing import Any, Dict, Optional

# ------------------------------------------------------------------ FORCE tier

FORCE_RULES = [
    {
        "id": "gas_leak",
        "pattern": r"(smell|odou?r|whiff)[^.]{0,30}gas|gas\s*(leak|smell|odou?r)|leaking\s+gas",
        "reason": "Possible gas leak reported",
        "guidance": (
            "Please leave the apartment now. Do not touch light switches, "
            "appliances, or anything that can spark, and do not light flames. "
            "Once outside, call 911 and your gas utility's 24-hour emergency line."
        ),
    },
    {
        "id": "carbon_monoxide",
        "pattern": r"carbon\s*monoxide|\bco\s*(alarm|detector)\b|monoxide\s*alarm",
        "reason": "Carbon monoxide alarm / exposure reported",
        "guidance": (
            "Get everyone (including pets) outside to fresh air right away and "
            "call 911 from outside. Do not re-enter until emergency services say "
            "it is safe."
        ),
    },
    {
        "id": "fire_smoke",
        "pattern": r"\bfire\b|on\s+fire|smoke\s+(coming|filling|everywhere)|smell\s+(of\s+)?smoke|something('s|\s+is)?\s+burning",
        "reason": "Fire or smoke reported",
        "guidance": (
            "If there is any fire or smoke, leave the apartment immediately, "
            "close doors behind you, use the stairs (not the elevator), and call "
            "911 from a safe place."
        ),
    },
    {
        "id": "person_trapped",
        "pattern": r"(stuck|trapped)\s+in\s+(the\s+)?(elevator|lift)|elevator[^.]{0,20}(stuck|trapped)",
        "reason": "Person trapped in elevator",
        "guidance": (
            "Stay calm and do not try to force the doors or climb out. Press the "
            "alarm/help button inside the elevator and call 911 if anyone is in "
            "distress. Help is being dispatched."
        ),
    },
]

# ------------------------------------------------------------------- FLAG tier

FLAG_RULES = [
    {"id": "sparks", "pattern": r"spark(s|ing)?|burning\s+smell\s+from|outlet[^.]{0,20}(hot|smoking)", "reason": "Electrical sparking / burning smell"},
    {"id": "exposed_wiring", "pattern": r"exposed\s+wir(e|es|ing)|wires?\s+(hanging|sticking)", "reason": "Exposed electrical wiring"},
    {"id": "flooding", "pattern": r"flood(ing|ed)?|burst\s+pipe|water\s+(is\s+)?(pouring|gushing|everywhere)|(pouring|gushing)\s+(from|through|out)", "reason": "Active flooding / burst pipe"},
    {"id": "sewage", "pattern": r"sewage|sewer\s+back(ing)?\s*up|toilet[^.]{0,30}overflow", "reason": "Sewage backup / overflow"},
    {"id": "no_heat", "pattern": r"no\s+heat|heat(ing)?\s+(is\s+)?(not\s+working|broken|out|off)|radiator[^.]{0,20}cold", "reason": "No heat reported"},
    {"id": "no_hot_water", "pattern": r"no\s+hot\s+water|water\s+is\s+(freezing|ice)\s*cold", "reason": "No hot water reported"},
    {"id": "ceiling_collapse", "pattern": r"ceiling[^.]{0,30}(collaps|caving|bulg|sagging|falling)", "reason": "Possible ceiling collapse"},
    {"id": "break_in", "pattern": r"break[-\s]?in|broke\s+into|door[^.]{0,30}(kicked|forced)", "reason": "Break-in / entry security compromised"},
    {"id": "lock_broken", "pattern": r"(front|entry|apartment)\s+door[^.]{0,30}(lock|won'?t\s+lock)|lock\s+(is\s+)?broken", "reason": "Entry door will not lock"},
]


def check(message: str) -> Dict[str, Any]:
    """Run the pre-filter. Returns a dict:

    {
      "force_escalate": bool,   # bypass the agent loop entirely
      "flag": bool,             # hazard flag passed to the supervisor
      "rule_id": str | None,
      "reason": str | None,
      "guidance": str | None,   # canned immediate-safety steps (FORCE tier only)
    }
    """
    text = (message or "").lower()

    for rule in FORCE_RULES:
        if re.search(rule["pattern"], text):
            return {
                "force_escalate": True,
                "flag": True,
                "rule_id": rule["id"],
                "reason": rule["reason"],
                "guidance": rule["guidance"],
            }

    for rule in FLAG_RULES:
        if re.search(rule["pattern"], text):
            return {
                "force_escalate": False,
                "flag": True,
                "rule_id": rule["id"],
                "reason": rule["reason"],
                "guidance": None,
            }

    return {"force_escalate": False, "flag": False, "rule_id": None, "reason": None, "guidance": None}
