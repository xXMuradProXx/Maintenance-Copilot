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
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from . import rag, safety, taxonomy, vendors
from .llm_client import get_llmod_client
from .state import (
    STATUS_AWAITING_TENANT,
    STATUS_ESCALATED,
    STATUS_NEEDS_INFO,
    STATUS_RESOLVED,
    STATUS_SCHEDULED,
    CaseState,
)

MODEL = os.getenv("LLMOD_MODEL", "MB5R2CF-azure/gpt-5.4-mini")
MAX_STEPS = 6          # supervisor loop budget (loop guard)
MAX_HISTORY = 12       # prior chat turns forwarded to the model

SUPERVISOR_MODULE = "SupervisorAgent"
EMERGENCY_RESPONSE_MODULE = "EmergencyResponseAgent"
LLM_MODULES = (SUPERVISOR_MODULE, EMERGENCY_RESPONSE_MODULE)
PUBLIC_MODULES = (
    "SafetyPreFilter",
    SUPERVISOR_MODULE,
    EMERGENCY_RESPONSE_MODULE,
    "TaxonomySearch",
    "GuidanceRetriever",
    "SchedulingTools",
    "SharedCaseState",
    "SupabaseAuditStore",
)

_client = None

_UNIT_PATTERN = re.compile(
    r"\b(?:apartment|apt\.?|unit)\s*"
    r"(?:(?:number|no\.?)\s*)?(?:is\s*)?[:#-]?\s*"
    r"((?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{0,9})\b",
    re.IGNORECASE,
)


def _extract_unit(message: str) -> str | None:
    """Extract only an explicitly labelled apartment/unit identifier."""
    match = _UNIT_PATTERN.search(message or "")
    return match.group(1).upper() if match else None


def _get_client():
    global _client
    if _client is None:
        _client = get_llmod_client()
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
- Scheduling is a demo simulation: slots are generated, appointments are recorded only in case \
state, and no vendor calendar is reserved or person notified. Say this plainly to the tenant.
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
2) Says the case is marked for urgent manager review, but no notification was sent by this demo, so
   the tenant should contact building management directly.
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
            "description": "Search the 641-row HPD problem taxonomy in Supabase with the tenant's own words. "
                           "Returns official candidate rows, mapped HPD urgency, historical frequency, "
                           "source provenance, and inferred vendor trade.",
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
            "description": "Semantic search over the official housing-code and HPD-source corpus. Returns source-grounded passages when that corpus has been indexed in Pinecone.",
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
            "description": "Generate deterministic demo windows for the given trade. These are not live vendor-calendar reservations.",
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
            "description": "Record a simulated appointment the tenant explicitly chose. No vendor is contacted or calendar reserved; slot_id must have been offered in this case.",
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
            "description": "Mark the case for human property-manager review. This demo does not send a notification.",
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
            case.citations.append(
                {
                    "title": r["title"],
                    "source": r.get("source"),
                    "file_name": r.get("file_name"),
                    "page": r.get("page"),
                    "section": r.get("section"),
                    "score": r["score"],
                }
            )
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
        return {
            "ok": True,
            "appointment": slot,
            "note": "Appointment recorded in demo state only; no contractor was contacted.",
        }

    if name == "ask_tenant":
        case.missing_info = list(args.get("missing_fields") or []) or case.missing_info
        if case.status not in (STATUS_ESCALATED,):
            case.status = STATUS_NEEDS_INFO
        return {"ok": True, "status": case.status}

    if name == "escalate_to_manager":
        case.status = STATUS_ESCALATED
        case.escalation_reason = args.get("reason", "unspecified")
        return {
            "ok": True,
            "status": case.status,
            "note": "Case marked for manager review; no notification was sent.",
        }

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


def _trace_prompt(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    """Represent the complete OpenAI-style message list in the required schema."""
    system_parts = [
        str(item.get("content", ""))
        for item in messages
        if item.get("role") == "system"
    ]
    conversation = [item for item in messages if item.get("role") != "system"]
    return {
        "system_prompt": "\n\n".join(system_parts),
        # Later agent iterations include assistant tool calls and tool results;
        # JSON preserves that complete context while retaining the required
        # user_prompt string field.
        "user_prompt": json.dumps(conversation, ensure_ascii=False),
    }


def _trace_response(response: Any) -> Dict[str, Any]:
    """Convert an SDK response into JSON-safe audit data."""
    choice = response.choices[0].message
    tool_calls = []
    for call in choice.tool_calls or []:
        tool_calls.append(
            {
                "id": call.id,
                "name": call.function.name,
                "arguments": call.function.arguments,
            }
        )
    usage = getattr(response, "usage", None)
    return {
        "model": getattr(response, "model", MODEL),
        "content": choice.content or "",
        "tool_calls": tool_calls,
        "token_usage": {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        },
    }


def _call_llm(
    case: CaseState,
    module: str,
    messages: List[Dict[str, Any]],
    **kwargs: Any,
) -> Any:
    """Make one model call and record it, including failures, exactly once."""
    if module not in LLM_MODULES:
        raise ValueError(
            f"Unknown LLM module '{module}'. Expected one of: "
            + ", ".join(LLM_MODULES)
        )
    prompt = _trace_prompt(messages)
    try:
        response = _get_client().chat.completions.create(
            model=MODEL,
            messages=messages,
            **kwargs,
        )
    except Exception as exc:
        case.llm_steps.append(
            {
                "module": module,
                "prompt": prompt,
                "response": {
                    "model": MODEL,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            }
        )
        raise
    case.llm_steps.append(
        {"module": module, "prompt": prompt, "response": _trace_response(response)}
    )
    return response


def run_case(message: str, history: List[Dict[str, Any]], case: CaseState) -> Tuple[str, CaseState]:
    """Process one tenant message through the full pipeline. Returns (reply, case)."""

    # ---- 1. Safety Pre-Filter (rule-based, runs before any LLM call) ----
    case.unit = case.unit or _extract_unit(message)
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

    reply: str = ""

    for _step in range(MAX_STEPS):
        response = _call_llm(
            case,
            SUPERVISOR_MODULE,
            messages,
            tools=TOOLS,
            tool_choice="auto",
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
        reply = (
            "Thanks for your message — I've logged the issue and marked it for property "
            "manager review. This demo does not send notifications, so please contact building "
            "management directly."
        )
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
        case.citations.append(
            {
                "title": r["title"],
                "source": r.get("source"),
                "file_name": r.get("file_name"),
                "page": r.get("page"),
                "section": r.get("section"),
                "score": r["score"],
            }
        )
        page_note = f", page {r.get('page')}" if r.get("page") else ""
        snippets += f"- [{r['title']}{page_note}] {r['text'][:300]}\n"
    if retrieval.get("results"):
        case.add_trace("tool:retrieve_guidance", "observe",
                       "; ".join(r["title"] for r in retrieval["results"][:3]))

    unit_request = (
        "" if case.unit
        else " Please reply with your apartment number if you haven't shared it yet."
    )
    fallback_reply = (
        f"This looks like an emergency ({safety_result['reason'].lower()}). "
        f"{safety_result['guidance']} This case is marked for urgent property-manager review, "
        "but this demo does not send notifications, so contact building management directly."
        f"{unit_request}"
    )

    try:
        messages = [
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
            ]
        response = _call_llm(
            case,
            EMERGENCY_RESPONSE_MODULE,
            messages,
        )
        reply = (response.choices[0].message.content or "").strip() or fallback_reply
    except Exception:  # noqa: BLE001 — safety reply must always go out
        reply = fallback_reply

    case.add_trace("supervisor", "respond", reply[:160])
    return reply, case
