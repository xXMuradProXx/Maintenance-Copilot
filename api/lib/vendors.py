"""Approved-vendor directory + calendar (Scheduling sub-agent tools).

In production this would call the property manager's real vendor list and a
calendar API (Google Calendar, Housecall Pro, etc.). For the course demo the
directory is static and availability is generated deterministically relative
to "today", so the demo always has bookable slots.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

VENDORS: List[Dict[str, Any]] = [
    {"id": "PL-01", "name": "Rapid Rooter Plumbing", "trade": "plumber", "approved": True},
    {"id": "PL-02", "name": "BlueLine Plumbing & Heating", "trade": "plumber", "approved": True},
    {"id": "EL-01", "name": "Volt & Vane Electric", "trade": "electrician", "approved": True},
    {"id": "HV-01", "name": "Summit HVAC Services", "trade": "hvac", "approved": True},
    {"id": "EX-01", "name": "CityShield Pest Control", "trade": "exterminator", "approved": True},
    {"id": "LK-01", "name": "Keystone Locksmiths", "trade": "locksmith", "approved": True},
    {"id": "HM-01", "name": "Fixwell Handyman Co.", "trade": "handyman", "approved": True},
    {"id": "AP-01", "name": "HomeTech Appliance Repair", "trade": "appliance", "approved": True},
    {"id": "RM-01", "name": "ClearAir Mold Remediation", "trade": "remediation", "approved": True},
    {"id": "GL-01", "name": "PanePro Glass & Windows", "trade": "glazier", "approved": True},
    {"id": "EV-01", "name": "UpTown Elevator Service", "trade": "elevator", "approved": True},
    {"id": "GC-01", "name": "Anchor General Contracting", "trade": "contractor", "approved": True},
]

# Loose names the LLM might use -> canonical trade
TRADE_ALIASES = {
    "plumbing": "plumber", "plumber": "plumber",
    "electric": "electrician", "electrical": "electrician", "electrician": "electrician",
    "hvac": "hvac", "heating": "hvac", "heat": "hvac", "boiler": "hvac", "ac": "hvac",
    "pest": "exterminator", "pests": "exterminator", "pest control": "exterminator", "exterminator": "exterminator",
    "locksmith": "locksmith", "locks": "locksmith", "lock": "locksmith",
    "handyman": "handyman", "general": "handyman", "carpenter": "handyman",
    "appliance": "appliance", "appliances": "appliance",
    "mold": "remediation", "remediation": "remediation",
    "glass": "glazier", "glazier": "glazier", "window": "glazier", "windows": "glazier",
    "elevator": "elevator", "lift": "elevator",
    "contractor": "contractor", "structural": "contractor",
}

# (days_from_today, start_hour, end_hour)
_WINDOWS = [(1, 10, 12), (1, 14, 16), (2, 9, 11)]


def normalize_trade(trade: str) -> Optional[str]:
    return TRADE_ALIASES.get((trade or "").strip().lower())


def find_slots(trade: str) -> Dict[str, Any]:
    """Return the next open windows for approved vendors of the given trade."""
    canonical = normalize_trade(trade)
    if canonical is None:
        return {
            "ok": False,
            "error": f"Unknown trade '{trade}'. Known trades: "
                     + ", ".join(sorted(set(v["trade"] for v in VENDORS))),
            "slots": [],
        }

    matches = [v for v in VENDORS if v["trade"] == canonical and v["approved"]][:2]
    if not matches:
        return {"ok": False, "error": f"No approved vendor for trade '{canonical}'.", "slots": []}

    now = datetime.now()
    slots: List[Dict[str, Any]] = []
    for v in matches:
        windows = _WINDOWS[:2] if len(matches) > 1 else _WINDOWS
        for days, start, end in windows:
            day = now + timedelta(days=days)
            slots.append(
                {
                    "slot_id": f"{v['id']}-{day.strftime('%Y%m%d')}-{start:02d}",
                    "vendor_id": v["id"],
                    "vendor_name": v["name"],
                    "trade": canonical,
                    "date": day.strftime("%Y-%m-%d"),
                    "label": f"{day.strftime('%A, %b %d')}, {start}:00\u2013{end}:00",
                }
            )
    return {"ok": True, "trade": canonical, "slots": slots}


def resolve_slot(slot_id: str, offered_slots: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Look a slot_id up among slots previously offered in this case."""
    for slot in offered_slots or []:
        if slot.get("slot_id") == slot_id:
            return slot
    return None
