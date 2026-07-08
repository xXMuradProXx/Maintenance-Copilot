"""Supervisor Agent (the green box on the architecture slide).

Implements the agent workflow loop:

    tenant message -> Safety Pre-Filter -> Supervisor (LLM w/ tools)
        tools: classify_issue, record_work_order, retrieve_guidance (RAG),
               find_vendor_slots, book_appointment, ask_tenant,
               escalate_to_manager, mark_resolved
        every tool reads/writes the Shared Case State
    -> stop condition met -> supervisor sends the tenant-facing response

Loop guard (Autonomy Boundaries slide): at most MAX_STEPS supervisor
iterations; if the budget is exhausted without a terminal state, the case is
handed to the human manager.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple

from openai import OpenAI

from _lib import rag, safety, taxonomy, vendors
from _lib.state import (
    STATUS_AWAITING_TENANT,
    STATUS_ESCALATED,
    STATUS_NEEDS_INFO,
    STATUS_RESOLVED,
    STATUS_SCHEDULED,
    CaseState,
)

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_STEPS = 6          # supervisor loop budget (loop guard)
MAX_HISTORY = 12       # prior chat turns forwarded to the model

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


# --------------------------------------------------------------------- prompts

SYSTEM_PROMPT = """You are "Maintenance Copilot", the supervisor agent for a small property-management \
company. You triage incoming tenant maintenance messages and drive each case to exactly one next \
operational state: scheduled, waiting on the tenant, escalated to the human manager, or resolved.

Follow this decision stack, in order:
1. CLASSIFY — call classify_issue to map the tenant's words to a taxonomy problem code, then persist \
your pick with record_work_order (call it again whenever your understanding changes).
2. PRIORITIZE — urgency comes from the taxonomy and the safety pre-filter (EMERGENCY > URGENT > \
ROUTINE). Call retrieve_guidance when landlord obligations or urgency are unclear (heat/hot-water \
rules, hazard classes, mold, pests, security).
3. REFLECT — check the autonomy policy below before acting.
4. ACT — ask the tenant, offer appointment windows, book, or escalate.

AUTONOMY POLICY (hard rules):
- EMERGENCY urgency: call escalate_to_manager, give the tenant clear immediate-safety instructions, \
and do NOT schedule a vendor.
- For ROUTINE and URGENT issues with a clear classification, call find_vendor_slots and offer the \
tenant the returned windows (quote the labels exactly).
- Call book_appointment ONLY with a slot_id that was previously offered in this case AND that the \
tenant explicitly chose in their latest message. Never book on a guess.
- If the apartment/unit number or the problem's location is missing and needed, call ask_tenant and \
ask at most two short questions in your reply.
- Never invent vendors, time slots, laws, or policies. Ground any legal or urgency claim in \
retrieve_guidance results and mention the source title briefly (e.g., "per the heat and hot water \
policy"). If retrieval is unavailable, say the manager will confirm the policy detail.
- If the tenant confirms the problem is fixed, call mark_resolved.
- Escalate to the manager when: confidence is low, tools conflict, the tenant mentions legal action, \
a vulnerable person, or a repeat unresolved complaint, or the request is outside maintenance.

REPLY STYLE (tenant-facing): warm, plain language, 2–6 sentences, no markdown headings, no internal \
jargon (never mention tools, taxonomy rows, or "the LLM"). Confirm what you understood, state what \
happens next and who does what. Answer in the tenant's own language if they didn't write in English.

STOP: once this turn reaches a stop condition (question asked, slots offered, appointment booked, \
escalated, or resolved), write the tenant reply and stop calling tools."""

EMERGENCY_PROMPT = """EMERGENCY MODE. The rule-based safety pre-filter force-escalated this case.
Reason: {reason}

Write a short reply to the tenant (4–6 sentences, calm, plain language) that:
1) Leads with these immediate safety steps, in your own words but keeping every instruction: {guidance}
2) Tells them the property manager has been alerted and this is being handled as an emergency.
3) Asks for their apartment number ONLY if it is not already known ({unit}).
Do not offer or schedule any appointments. Do not add any other questions.

Relevant policy snippets (optional background, cite the title briefly if used):
{citations}"""


# ----------------------------------------------------------------------- tools

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "classify_issue",
            "description": "Search the HPD-style problem taxonomy with the tenant's own words. "
                           "Returns candidate rows with category, problem code, urgency label and vendor trade.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Key terms from the tenant message, e.g. 'sink clogged drains slowly'."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_work_order",
            "description": "Persist the structured work order into the shared case state. Call once the classification is chosen, and again if it changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "One-sentence plain description of the issue."},
                    "issue_category": {"type": "string"},
                    "problem_code": {"type": "string"},
                    "urgency": {"type": "string", "enum": ["EMERGENCY", "URGENT", "ROUTINE"]},
                    "vendor_trade": {"type": "string", "description": "e.g. plumber, electrician, hvac, exterminator, locksmith, handyman, appliance, remediation, glazier, elevator, contractor."},
                    "unit": {"type": "string", "description": "Apartment/unit number if the tenant stated it."},
                    "missing_info": {"type": "array", "items": {"type": "string"}, "description": "Facts still needed from the tenant."},
                },
                "required": ["summary", "issue_category", "problem_code", "urgency", "vendor_trade"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_guidance",
            "description": "Semantic search (RAG) over the housing code + HPD-style guidance corpus: heat/hot water rules, hazard classes and repair timeframes, leaks, mold, pests, electrical and gas safety, locks/security, communication playbook.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_vendor_slots",
            "description": "Check approved vendors' calendars for the given trade and return the next open appointment windows (each with a slot_id).",
            "parameters": {
                "type": "object",
                "properties": {"trade": {"type": "string"}},
                "required": ["trade"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book a window the tenant explicitly chose. slot_id must come from slots previously offered in this case.",
            "parameters": {
                "type": "object",
                "properties": {"slot_id": {"type": "string"}},
                "required": ["slot_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_tenant",
            "description": "Mark the case as waiting on the tenant for missing facts. Your final reply must contain the actual question(s).",
            "parameters": {
                "type": "object",
                "properties": {
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["missing_fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_manager",
            "description": "Hand the case to the human property manager (emergencies, low confidence, policy conflicts, legal threats, vulnerable tenants, repeat complaints).",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_resolved",
            "description": "Close the case after the tenant confirms the problem is fixed.",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"],
            },
        },
    },
]


def _dispatch_tool(name: str, args: Dict[str, Any], case: CaseState) -> Dict[str, Any]:
    """Run one tool against the shared case state and return its observation."""

    if name == "classify_issue":
        candidates = taxonomy.search(args.get("query", ""))
        return {"candidates": candidates}

    if name == "record_work_order":
        case.summary = args.get("summary") or case.summary
        case.issue_category = args.get("issue_category") or case.issue_category
        case.problem_code = args.get("problem_code") or case.problem_code
        case.urgency = args.get("urgency") or case.urgency
        case.vendor_trade = args.get("vendor_trade") or case.vendor_trade
        if args.get("unit"):
            case.unit = args["unit"]
        case.missing_info = list(args.get("missing_info") or [])
        return {"ok": True, "work_order": case.snapshot()}

    if name == "retrieve_guidance":
        result = rag.retrieve(args.get("query", ""))
        for r in result.get("results", []):
            case.citations.append({"title": r["title"], "score": r["score"]})
        case.citations = case.citations[-8:]
        return result

    if name == "find_vendor_slots":
        result = vendors.find_slots(args.get("trade", case.vendor_trade or ""))
        if result.get("ok"):
            case.offered_slots = result["slots"]
            if case.status not in (STATUS_SCHEDULED, STATUS_ESCALATED, STATUS_RESOLVED):
                case.status = STATUS_AWAITING_TENANT
        return result

    if name == "book_appointment":
        slot = vendors.resolve_slot(args.get("slot_id", ""), case.offered_slots)
        if slot is None:
            return {
                "ok": False,
                "error": "slot_id was never offered in this case. Offer slots with "
                         "find_vendor_slots and let the tenant choose first.",
            }
        case.appointment = slot
        case.status = STATUS_SCHEDULED
        return {"ok": True, "appointment": slot,
                "note": "Contractor notified with unit, issue summary and access instructions."}

    if name == "ask_tenant":
        case.missing_info = list(args.get("missing_fields") or []) or case.missing_info
        if case.status not in (STATUS_ESCALATED,):
            case.status = STATUS_NEEDS_INFO
        return {"ok": True, "status": case.status}

    if name == "escalate_to_manager":
        case.status = STATUS_ESCALATED
        case.escalation_reason = args.get("reason", "unspecified")
        return {"ok": True, "status": case.status,
                "note": "Manager notified with the full case trace."}

    if name == "mark_resolved":
        case.status = STATUS_RESOLVED
        return {"ok": True, "status": case.status, "note": args.get("note", "")}

    return {"ok": False, "error": f"Unknown tool '{name}'."}


# ------------------------------------------------------------------- main loop

def _context_message(case: CaseState, safety_result: Dict[str, Any]) -> Dict[str, str]:
    flag_note = "none"
    if safety_result["flag"]:
        flag_note = (f"FLAGGED — {safety_result['reason']}. Treat as EMERGENCY unless the "
                     "conversation clearly contradicts it; prefer escalation over scheduling.")
    return {
        "role": "system",
        "content": (
            f"Today is {datetime.now().strftime('%A, %Y-%m-%d')}. "
            f"Message channel: {case.channel}.\n"
            f"SAFETY PRE-FILTER: {flag_note}\n"
            f"CURRENT SHARED CASE STATE (JSON): {json.dumps(case.snapshot(), ensure_ascii=False)}"
        ),
    }


def _clean_history(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    cleaned = []
    for msg in history or []:
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content[:4000]})
    return cleaned[-MAX_HISTORY:]


def run_case(message: str, history: List[Dict[str, Any]], case: CaseState) -> Tuple[str, CaseState]:
    """Process one tenant message through the full pipeline. Returns (reply, case)."""

    # ---- 1. Safety Pre-Filter (rule-based, runs before any LLM call) ----
    safety_result = safety.check(message)
    if safety_result["flag"]:
        case.safety_flag = True
        case.safety_reason = safety_result["reason"]
        case.add_trace("safety_filter", "flag", safety_result["reason"])
    else:
        case.add_trace("safety_filter", "pass", "no emergency keywords matched")

    if safety_result["force_escalate"]:
        return _emergency_path(message, case, safety_result)

    # ---- 2. Supervisor agent loop ----
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        _context_message(case, safety_result),
        *_clean_history(history),
        {"role": "user", "content": message},
    ]

    client = _get_client()
    reply: str = ""

    for _step in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )
        choice = response.choices[0].message

        if not choice.tool_calls:
            reply = (choice.content or "").strip()
            break

        # Feed the assistant's tool-call turn back into the conversation.
        messages.append(
            {
                "role": "assistant",
                "content": choice.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in choice.tool_calls
                ],
            }
        )

        for tc in choice.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                if not isinstance(args, dict):
                    args = {}
            except (json.JSONDecodeError, TypeError):
                args = {}

            try:
                observation = _dispatch_tool(tc.function.name, args, case)
            except Exception as exc:  # noqa: BLE001 — a tool bug must not kill the case
                observation = {"ok": False, "error": f"Tool failed: {type(exc).__name__}: {exc}"}

            case.add_trace(f"tool:{tc.function.name}", "call",
                           json.dumps(args, ensure_ascii=False)[:160])
            case.add_trace(f"tool:{tc.function.name}", "observe",
                           json.dumps(observation, ensure_ascii=False)[:240])
            messages.append(
                {"role": "tool", "tool_call_id": tc.id,
                 "content": json.dumps(observation, ensure_ascii=False)}
            )

    # ---- 3. Loop guard (Autonomy Boundaries slide) ----
    if not reply:
        if not case.is_terminal():
            case.status = STATUS_ESCALATED
            case.escalation_reason = "Loop guard: step budget exhausted without a terminal state."
        case.add_trace("supervisor", "loop_guard", "step budget exhausted -> manager handoff")
        reply = ("Thanks for your message — I've logged the issue and passed it directly to the "
                 "property manager, who will follow up with you shortly.")
    else:
        case.add_trace("supervisor", "respond", reply[:160])

    return reply, case


def _emergency_path(message: str, case: CaseState, safety_result: Dict[str, Any]) -> Tuple[str, CaseState]:
    """FORCE tier: bypass the agent loop. Deterministic escalation + safety guidance."""
    case.status = STATUS_ESCALATED
    case.urgency = "EMERGENCY"
    case.escalation_reason = f"Safety pre-filter: {safety_result['reason']}"
    case.add_trace("safety_filter", "force_escalate", safety_result["reason"])

    # Best-effort classification so the work order is still filled in.
    candidates = taxonomy.search(message)
    if candidates and candidates[0]["score"] > 0:
        top = candidates[0]
        case.issue_category = case.issue_category or top["category"]
        case.problem_code = case.problem_code or top["code"]
        case.vendor_trade = case.vendor_trade or top["trade"]
    case.summary = case.summary or safety_result["reason"]

    # Best-effort retrieval so evidence still travels with the work order.
    retrieval = rag.retrieve(safety_result["reason"])
    snippets = ""
    for r in retrieval.get("results", [])[:2]:
        case.citations.append({"title": r["title"], "score": r["score"]})
        snippets += f"- [{r['title']}] {r['text'][:300]}\n"
    if retrieval.get("results"):
        case.add_trace("tool:retrieve_guidance", "observe",
                       "; ".join(r["title"] for r in retrieval["results"][:3]))

    fallback_reply = (
        f"This looks like an emergency ({safety_result['reason'].lower()}). "
        f"{safety_result['guidance']} The property manager has been alerted and is treating "
        "this as an emergency. Please reply with your apartment number if you haven't shared it yet."
    )

    try:
        response = _get_client().chat.completions.create(
            model=MODEL,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": EMERGENCY_PROMPT.format(
                        reason=safety_result["reason"],
                        guidance=safety_result["guidance"],
                        unit=case.unit or "unknown",
                        citations=snippets or "none available",
                    ),
                },
                {"role": "user", "content": message},
            ],
        )
        reply = (response.choices[0].message.content or "").strip() or fallback_reply
    except Exception:  # noqa: BLE001 — safety reply must always go out
        reply = fallback_reply

    case.add_trace("supervisor", "respond", reply[:160])
    return reply, case
