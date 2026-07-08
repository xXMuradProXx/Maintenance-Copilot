"""HPD-style problem taxonomy (structured data source).

The presentation references an HPD complaint taxonomy of 642 category /
problem-code rows with urgency labels. This module ships a representative,
hand-curated subset so the app is fully self-contained; to use the full
taxonomy, extend TAXONOMY (same shape) or load it from a CSV at import time.

Urgency labels:
  EMERGENCY -> immediately hazardous; escalate, never auto-schedule
  URGENT    -> hazardous; schedule fast (24-72h)
  ROUTINE   -> non-hazardous; normal scheduling
"""

import re
from typing import Any, Dict, List

TAXONOMY: List[Dict[str, Any]] = [
    # --- HEAT / HOT WATER ---
    {"category": "HEAT/HOT WATER", "code": "NO HEAT", "urgency": "EMERGENCY", "trade": "hvac",
     "keywords": ["no heat", "heat not working", "heater broken", "radiator cold", "freezing", "heat is off", "boiler"]},
    {"category": "HEAT/HOT WATER", "code": "INADEQUATE HEAT", "urgency": "URGENT", "trade": "hvac",
     "keywords": ["not warm enough", "barely warm", "weak heat", "apartment cold", "low heat"]},
    {"category": "HEAT/HOT WATER", "code": "NO HOT WATER", "urgency": "EMERGENCY", "trade": "plumber",
     "keywords": ["no hot water", "cold water only", "water heater", "shower cold"]},
    {"category": "HEAT/HOT WATER", "code": "WATER TOO HOT / SCALDING", "urgency": "URGENT", "trade": "plumber",
     "keywords": ["scalding", "water too hot", "burns"]},

    # --- PLUMBING ---
    {"category": "PLUMBING", "code": "WATER LEAK", "urgency": "URGENT", "trade": "plumber",
     "keywords": ["leak", "leaking", "dripping", "water damage", "wet wall", "damp"]},
    {"category": "PLUMBING", "code": "CEILING LEAK", "urgency": "URGENT", "trade": "plumber",
     "keywords": ["ceiling leaking", "water from ceiling", "ceiling drip", "upstairs leak", "water near the light"]},
    {"category": "PLUMBING", "code": "BURST PIPE / FLOODING", "urgency": "EMERGENCY", "trade": "plumber",
     "keywords": ["burst pipe", "flooding", "flooded", "water pouring", "water everywhere", "gushing"]},
    {"category": "PLUMBING", "code": "CLOGGED DRAIN", "urgency": "ROUTINE", "trade": "plumber",
     "keywords": ["clogged", "drain", "draining slowly", "sink blocked", "slow drain", "backed up sink"]},
    {"category": "PLUMBING", "code": "TOILET NOT WORKING", "urgency": "URGENT", "trade": "plumber",
     "keywords": ["toilet", "won't flush", "toilet broken", "toilet running", "toilet clogged"]},
    {"category": "PLUMBING", "code": "NO WATER", "urgency": "EMERGENCY", "trade": "plumber",
     "keywords": ["no water", "water shut off", "no running water"]},
    {"category": "PLUMBING", "code": "LOW WATER PRESSURE", "urgency": "ROUTINE", "trade": "plumber",
     "keywords": ["low pressure", "water pressure", "trickle"]},
    {"category": "SEWAGE", "code": "SEWAGE BACKUP", "urgency": "EMERGENCY", "trade": "plumber",
     "keywords": ["sewage", "sewer", "backing up", "overflow", "smells like sewage"]},

    # --- ELECTRIC ---
    {"category": "ELECTRIC", "code": "SPARKS / BURNING SMELL", "urgency": "EMERGENCY", "trade": "electrician",
     "keywords": ["sparks", "sparking", "burning smell", "outlet hot", "smoking outlet", "electric thing sparks"]},
    {"category": "ELECTRIC", "code": "EXPOSED WIRING", "urgency": "EMERGENCY", "trade": "electrician",
     "keywords": ["exposed wire", "wires hanging", "bare wires"]},
    {"category": "ELECTRIC", "code": "NO POWER IN UNIT", "urgency": "URGENT", "trade": "electrician",
     "keywords": ["no power", "power out", "electricity out", "breaker keeps tripping", "blackout in apartment"]},
    {"category": "ELECTRIC", "code": "OUTLET NOT WORKING", "urgency": "ROUTINE", "trade": "electrician",
     "keywords": ["outlet not working", "socket dead", "plug not working"]},
    {"category": "ELECTRIC", "code": "LIGHT FIXTURE DEFECTIVE", "urgency": "ROUTINE", "trade": "electrician",
     "keywords": ["light not working", "light fixture", "flickering light", "bulb keeps"]},

    # --- GAS / APPLIANCES ---
    {"category": "GAS", "code": "GAS ODOR / SUSPECTED LEAK", "urgency": "EMERGENCY", "trade": "utility",
     "keywords": ["gas smell", "smell gas", "gas leak", "gas odor"]},
    {"category": "APPLIANCE", "code": "STOVE / OVEN DEFECTIVE", "urgency": "ROUTINE", "trade": "appliance",
     "keywords": ["stove", "oven", "burner", "range not working"]},
    {"category": "APPLIANCE", "code": "REFRIGERATOR NOT COOLING", "urgency": "URGENT", "trade": "appliance",
     "keywords": ["fridge", "refrigerator", "not cooling", "freezer", "food spoiling"]},
    {"category": "APPLIANCE", "code": "WASHER / DRYER DEFECTIVE", "urgency": "ROUTINE", "trade": "appliance",
     "keywords": ["washer", "washing machine", "dryer", "laundry"]},

    # --- DOORS / WINDOWS / SECURITY ---
    {"category": "DOOR/WINDOW", "code": "ENTRY DOOR LOCK BROKEN", "urgency": "URGENT", "trade": "locksmith",
     "keywords": ["lock broken", "won't lock", "door lock", "can't lock", "key stuck", "deadbolt"]},
    {"category": "DOOR/WINDOW", "code": "DOOR DAMAGED (BREAK-IN)", "urgency": "EMERGENCY", "trade": "locksmith",
     "keywords": ["break in", "broke into", "door kicked", "forced open", "burglary"]},
    {"category": "DOOR/WINDOW", "code": "LOCKOUT", "urgency": "URGENT", "trade": "locksmith",
     "keywords": ["locked out", "lost my keys", "lockout"]},
    {"category": "DOOR/WINDOW", "code": "BROKEN WINDOW GLASS", "urgency": "URGENT", "trade": "glazier",
     "keywords": ["broken window", "shattered", "cracked glass", "window glass"]},
    {"category": "DOOR/WINDOW", "code": "WINDOW WON'T CLOSE / DRAFT", "urgency": "ROUTINE", "trade": "handyman",
     "keywords": ["window won't close", "window stuck", "draft", "drafty"]},

    # --- PESTS ---
    {"category": "PESTS", "code": "RODENTS", "urgency": "URGENT", "trade": "exterminator",
     "keywords": ["mice", "mouse", "rats", "rat", "rodent", "droppings"]},
    {"category": "PESTS", "code": "ROACHES / INSECTS", "urgency": "URGENT", "trade": "exterminator",
     "keywords": ["roach", "cockroach", "ants", "insects", "bugs in kitchen"]},
    {"category": "PESTS", "code": "BED BUGS", "urgency": "URGENT", "trade": "exterminator",
     "keywords": ["bed bug", "bedbug", "bites at night"]},

    # --- MOLD / WATER DAMAGE / STRUCTURE ---
    {"category": "MOLD", "code": "VISIBLE MOLD", "urgency": "URGENT", "trade": "remediation",
     "keywords": ["mold", "mould", "mildew", "black spots wall", "smells bad wall", "musty"]},
    {"category": "STRUCTURE", "code": "CEILING COLLAPSE / BULGE", "urgency": "EMERGENCY", "trade": "contractor",
     "keywords": ["ceiling collapsed", "ceiling caving", "ceiling bulge", "ceiling sagging", "ceiling falling"]},
    {"category": "STRUCTURE", "code": "WALL / PLASTER DAMAGE", "urgency": "ROUTINE", "trade": "handyman",
     "keywords": ["peeling paint", "plaster", "crack in wall", "hole in wall"]},
    {"category": "STRUCTURE", "code": "FLOOR DAMAGED", "urgency": "ROUTINE", "trade": "handyman",
     "keywords": ["floor", "tile broken", "loose floorboard"]},

    # --- SAFETY EQUIPMENT / BUILDING ---
    {"category": "SAFETY", "code": "SMOKE / CO DETECTOR DEFECTIVE", "urgency": "URGENT", "trade": "handyman",
     "keywords": ["smoke detector", "co detector", "detector beeping", "alarm beeping", "chirping"]},
    {"category": "BUILDING", "code": "ELEVATOR OUT OF SERVICE", "urgency": "URGENT", "trade": "elevator",
     "keywords": ["elevator broken", "elevator not working", "lift broken", "elevator out"]},
    {"category": "GENERAL", "code": "OTHER / UNCLASSIFIED", "urgency": "ROUTINE", "trade": "handyman",
     "keywords": []},
]


def search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Keyword-score the taxonomy against free text and return top candidates.

    Phrase keywords are matched as substrings; single-word keywords are
    matched on word boundaries. The supervisor LLM makes the final pick.
    """
    text = " " + re.sub(r"[^a-z0-9\s']", " ", (query or "").lower()) + " "
    scored = []
    for row in TAXONOMY:
        score = 0
        for kw in row["keywords"]:
            if " " in kw:
                if kw in text:
                    score += 2
            else:
                if re.search(r"\b" + re.escape(kw) + r"\b", text):
                    score += 1
        if score > 0:
            scored.append({**{k: row[k] for k in ("category", "code", "urgency", "trade")}, "score": score})

    scored.sort(key=lambda r: r["score"], reverse=True)
    if not scored:
        return [{"category": "GENERAL", "code": "OTHER / UNCLASSIFIED", "urgency": "ROUTINE",
                 "trade": "handyman", "score": 0}]
    return scored[:top_k]
