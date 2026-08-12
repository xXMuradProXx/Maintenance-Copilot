"""Supabase-backed HPD problem taxonomy.

The primary source is the 641-row grouped HPD dataset in Supabase. A small
local subset remains only as a graceful outage fallback; database results are
clearly marked so the supervisor and trace can distinguish their provenance.

Urgency labels:
  EMERGENCY -> immediately hazardous; escalate, never auto-schedule
  URGENT    -> hazardous; schedule fast (24-72h)
  ROUTINE   -> non-hazardous; normal scheduling
"""

import re
from typing import Any, Dict, List

from .repositories import DatabaseOperationError, TaxonomyRepository
from .supabase_client import SupabaseConfigurationError

LOCAL_FALLBACK_TAXONOMY: List[Dict[str, Any]] = [
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


_repository = None


# Tenant language rarely mirrors HPD's administrative labels. These probes
# translate common symptom wording into phrases that are actually present in
# the imported taxonomy. Supabase remains the source of every returned row.
_QUERY_EXPANSIONS = (
    (("slow drain", "drains slowly", "draining slowly", "clogged", "blocked drain"),
     "plumbing drain pipe clogged"),
    (("wet wall", "damp wall", "wet ceiling", "damp ceiling", "water stain"),
     "water leaks from ceiling wall damp wet"),
    (("musty", "mildew", "mold", "mould", "wall smells bad", "ceiling smells bad"),
     "mold mold mildew"),
    (("spark", "sparking"), "electric fixture sparks when turned on"),
    (("no heat", "heat is off", "radiator cold"), "heating no heat"),
    (("no hot water", "cold water only", "shower cold"), "heat hot water no hot water"),
    (("sewage", "sewer", "wastewater"), "sewage raw sewage accumulation"),
    (("roach", "cockroach", "mice", "mouse", "rat", "rodent", "bedbug", "bed bug"),
     "unsanitary condition pests rodents insects"),
)


def _get_repository() -> TaxonomyRepository:
    global _repository
    if _repository is None:
        _repository = TaxonomyRepository()
    return _repository


def _infer_trade(category: str, minor_category: str, problem_code: str) -> str:
    """Map official HPD labels to the scheduling trade vocabulary."""
    category = (category or "").upper()
    text = f"{category} {minor_category or ''} {problem_code or ''}".upper()

    if "GAS LEAK" in text or "GAS ODOR" in text:
        return "utility"
    if category == "ELECTRIC" or any(word in text for word in ("WIRING", "OUTLET", "ELECTRIC")):
        return "electrician"
    if category == "ELEVATOR" or "ELEVATOR" in text:
        return "elevator"
    if "HOT WATER" in text and "NO HEAT" not in text and "HEATING" not in category:
        return "plumber"
    if category in {"HEATING", "HEAT/HOT WATER"} or any(
        word in text for word in ("BOILER", "RADIATOR", "HEAT-PLANT")
    ):
        return "hvac"
    if category in {"PLUMBING", "WATER LEAK"} or any(
        word in text for word in ("DRAIN", "TOILET", "SEWAGE", "PIPE", "FAUCET", "LEAK")
    ):
        return "plumber"
    if any(word in text for word in ("RODENT", "MICE", "MOUSE", "RAT", "ROACH", "BEDBUG", "PEST", "VERMIN")):
        return "exterminator"
    if any(word in text for word in ("MOLD", "MOULD", "MILDEW")):
        return "remediation"
    if category == "APPLIANCE":
        return "appliance"
    if any(word in text for word in ("LOCK", "DOOR", "INTERCOM")):
        return "locksmith"
    if any(word in text for word in ("WINDOW GLASS", "BROKEN WINDOW", "SHATTERED GLASS")):
        return "glazier"
    if category in {"CONSTRUCTION", "OUTSIDE BUILDING"}:
        return "contractor"
    return "handyman"


def _search_local(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Keyword fallback used only when Supabase cannot be reached.

    Phrase keywords are matched as substrings; single-word keywords are
    matched on word boundaries.
    """
    text = " " + re.sub(r"[^a-z0-9\s']", " ", (query or "").lower()) + " "
    scored = []
    for row in LOCAL_FALLBACK_TAXONOMY:
        score = 0
        for kw in row["keywords"]:
            if " " in kw:
                if kw in text:
                    score += 2
            else:
                if re.search(r"\b" + re.escape(kw) + r"\b", text):
                    score += 1
        if score > 0:
            scored.append(
                {
                    **{k: row[k] for k in ("category", "code", "urgency", "trade")},
                    "score": score,
                    "source": "local_fallback",
                }
            )

    scored.sort(key=lambda r: r["score"], reverse=True)
    if not scored:
        return [{"category": "GENERAL", "code": "OTHER / UNCLASSIFIED", "urgency": "ROUTINE",
                 "trade": "handyman", "score": 0, "source": "local_fallback"}]
    return scored[:top_k]


def _search_probes(query: str) -> List[str]:
    """Return the original query plus a few HPD-vocabulary expansions."""
    lowered = query.lower()
    probes = [query]
    if "drain" in lowered and any(word in lowered for word in ("slow", "clog", "block")):
        probes.append("plumbing drain pipe clogged")
    if any(place in lowered for place in ("wall", "ceiling")) and any(
        symptom in lowered for symptom in ("wet", "damp", "water stain")
    ):
        probes.append("water leaks from ceiling wall damp wet")
    if any(symptom in lowered for symptom in ("musty", "mildew", "mold", "mould")) or (
        "smell" in lowered
        and any(context in lowered for context in ("wall", "ceiling", "wet", "damp"))
    ):
        probes.append("mold mold mildew")
    for triggers, expansion in _QUERY_EXPANSIONS:
        if any(trigger in lowered for trigger in triggers):
            probes.append(expansion)
    # Avoid excessive network calls for messages containing many symptoms.
    return list(dict.fromkeys(probes))[:4]


def search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Search Supabase and return de-duplicated, frequency-grounded candidates."""
    query = (query or "").strip()
    if not query:
        return _search_local(query, top_k)

    try:
        # Fetch extra rows because the official dataset can contain the same
        # problem code under multiple raw urgency types. Search the original
        # wording and relevant HPD-vocabulary expansions, then merge them.
        database_rows = []
        for probe in _search_probes(query):
            for row in _get_repository().search(
                probe,
                top_k=min(max(top_k * 4, 10), 20),
            ):
                database_rows.append({**row, "match_basis": probe})
    except (DatabaseOperationError, SupabaseConfigurationError):
        return _search_local(query, top_k)

    grouped: Dict[tuple, Dict[Any, Dict[str, Any]]] = {}
    for row in database_rows:
        key = (
            row.get("major_category", ""),
            row.get("minor_category", ""),
            row.get("problem_code", ""),
        )
        row_key = row.get("id") or (
            row.get("raw_type"),
            row.get("urgency"),
            row.get("complaint_count"),
        )
        existing = grouped.setdefault(key, {}).get(row_key)
        if existing is None or float(row.get("similarity_score") or 0.0) > float(
            existing.get("similarity_score") or 0.0
        ):
            grouped[key][row_key] = row

    candidates = []
    for (category, minor_category, problem_code), rows_by_id in grouped.items():
        rows = list(rows_by_id.values())
        majority = max(rows, key=lambda item: int(item.get("complaint_count") or 0))
        total_count = sum(int(item.get("complaint_count") or 0) for item in rows)
        best_match = max(rows, key=lambda item: float(item.get("similarity_score") or 0.0))
        similarity = float(best_match.get("similarity_score") or 0.0)
        candidates.append(
            {
                "category": category,
                "minor_category": minor_category,
                "code": problem_code,
                "urgency": majority.get("urgency", "ROUTINE"),
                "raw_type": majority.get("raw_type"),
                "trade": _infer_trade(category, minor_category, problem_code),
                "complaint_count": total_count,
                "score": round(similarity, 4),
                "match_basis": best_match.get("match_basis", query),
                "source": "supabase:hpd_taxonomy",
            }
        )

    candidates.sort(
        key=lambda item: (item["score"], item["complaint_count"]),
        reverse=True,
    )
    return candidates[:top_k] or _search_local(query, top_k)
