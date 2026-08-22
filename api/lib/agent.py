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
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from . import rag, safety, taxonomy, tenant_guidance, vendors
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


def _detect_policy_flags(message: str) -> List[str]:
    """Detect manager-review gates from tenant text, independently of the LLM."""
    text = (message or "").lower()
    flags = []
    patterns = (
        ("legal_threat", r"\b(lawsuit|lawyer|attorney|sue|legal action|housing court)\b"),
        ("vulnerable_tenant", r"\b(infant|newborn|baby|elderly|disabled|pregnant|wheelchair|oxygen tank)\b"),
        ("repeat_unresolved", r"\b(still not fixed|not fixed yet|again|third time|fourth time|keeps happening)\b"),
        ("out_of_scope", r"\b(write (an? )?email|book (a )?flight|homework|stock price|weather forecast)\b"),
    )
    for flag, pattern in patterns:
        if re.search(pattern, text):
            flags.append(flag)
    return flags


def _get_client():
    global _client
    if _client is None:
        _client = get_llmod_client()
    return _client


# --------------------------------------------------------------------- prompts

SYSTEM_PROMPT = """You are "Maintenance Copilot", the supervisor agent for a small property-management \
company. You triage incoming tenant maintenance messages and drive each case to exactly one next \
operational state: scheduled, waiting on the tenant, escalated to the human manager, or resolved. \
Reduce routine manager work while staying inside deterministic safety gates; manager review is an \
exception, not the default.

Follow this decision stack, in order:
1. CLASSIFY — call classify_issue to map the tenant's words to a taxonomy problem code, then persist \
your pick with record_work_order (call it again whenever your understanding changes).
2. PRIORITIZE — the taxonomy urgency is a municipal repair-priority label, not proof of immediate \
life-safety danger. Persist it as taxonomy_urgency. Deterministic policy sets operational urgency. \
Before you call record_work_order for any heat, hot water, mold, pest, leak, sewage, or \
security/lock issue, call retrieve_guidance once and cite the source title and section briefly in \
your reply. For other issues call it only when an official obligation or policy fact is needed. It \
is never a source for ordinary DIY repair instructions.
3. REFLECT — check the autonomy policy below before acting.
4. ACT — call get_tenant_guidance for low-risk containment steps and routing questions, then ask the \
tenant and offer simulated appointment windows in the same turn when the trade is clear.

AUTONOMY POLICY (hard rules):
- Only a force-escalation result from SafetyPreFilter is an automatic emergency manager handoff. \
That path runs before you. Never escalate merely because the HPD taxonomy says EMERGENCY.
- Never record a problem_code the tenant's words do not support. If the message does not identify \
what is actually wrong, call ask_tenant first and do not call record_work_order with a guessed code. \
If you must record before the tenant answers, use the most general applicable category with \
taxonomy_urgency ROUTINE.
- classify_issue returns ranked candidates, not a decision. Choosing a specific code such as \
"LEAKING INTO OTHER APARTMENT" requires the tenant to have actually described that condition.
- Call escalate_to_manager only for an evidence-backed gate in CURRENT SHARED CASE STATE: a safety \
flag that cannot be handled through urgent routing, legal threat, vulnerable tenant, repeat unresolved \
complaint, out-of-scope request, verified tool conflict, or exhausted loop. The tool rejects unsupported escalation.
- For an ordinary clogged toilet with no stated overflow or sewage, do not escalate. Give the safe \
steps from get_tenant_guidance; ask whether the bowl is overflowing/rising and whether another toilet \
works; and offer simulated plumber windows in the same reply.
- For other ROUTINE and URGENT issues with a clear trade, call find_vendor_slots and offer 2–3 \
returned windows. Include vendor name, exact label, and an option number so the tenant can select it.
- Call book_appointment ONLY with a slot_id that was previously offered in this case AND that the \
tenant explicitly chose in their latest message by slot ID, exact label, or unambiguous option number. \
The tool independently verifies the selection. Never book on a guess.
- Scheduling is a demo simulation: slots are generated, appointments are recorded only in case \
state, and no vendor calendar is reserved or person notified. Say this plainly to the tenant.
- Ask at most two short questions that materially change safety, urgency, or routing. When the trade \
is clear, asking questions does not prevent you from offering simulated slots in that turn.
- Give only the reversible, low-risk steps returned by get_tenant_guidance. Do not tell a tenant to \
dismantle a fixture, use chemicals, handle electrical parts, or perform a hazardous repair.
- Never invent vendors, time slots, laws, or policies. Ground legal or policy claims in \
retrieve_guidance results and mention the source title briefly. If retrieval is unavailable, say the \
policy detail could not be confirmed; do not escalate a routine repair for that reason alone.
- If the tenant confirms the problem is fixed, call mark_resolved.
- Do not use low confidence as a shortcut to manager review. Ask focused questions first. Escalate \
only if uncertainty remains after questions or an allowed gate requires human judgment.

REPLY STYLE (tenant-facing): warm, plain language, 3–8 sentences, no markdown headings, no internal \
jargon (never mention tools, taxonomy rows, or "the LLM"). Confirm what you understood, give safe \
steps, ask necessary questions, and state what happens next. Answer in the tenant's own language if \
they didn't write in English.

STOP: once this turn reaches a stop condition (questions asked with useful next steps, slots offered, \
appointment booked, escalated, or resolved), write the tenant reply and stop calling tools."""

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

ROUTINE_RESPONSE_PROMPT = """You are the tenant-facing voice of Maintenance Copilot.
Rewrite the approved operational draft into warm, concise plain language while preserving every:
- safety or containment instruction;
- question;
- numbered vendor option, vendor name, and time label;
- statement that scheduling is only a simulation and no calendar/person was contacted.

Do not add a manager escalation, legal claim, diagnosis, repair instruction, vendor, or time. Do not
say anything was booked. Return only the tenant-facing reply, without a heading or markdown."""


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
                    "taxonomy_urgency": {"type": "string", "enum": ["EMERGENCY", "URGENT", "ROUTINE"], "description": "Copy the chosen taxonomy candidate's source urgency here; deterministic policy normalizes operational urgency."},
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
            "name": "get_tenant_guidance",
            "description": "Return deterministic, low-risk containment steps and up to two questions that change safety, urgency, or routing. Use this for practical tenant guidance; do not invent DIY steps.",
            "parameters": {"type": "object", "properties": {}},
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


def _normalize_operational_urgency(
    taxonomy_urgency: str | None,
    safety_flag: bool,
) -> str:
    """Map source repair priority without inventing a life-safety emergency."""
    if safety_flag or taxonomy_urgency in {"EMERGENCY", "URGENT"}:
        return "URGENT"
    return "ROUTINE"


def _dispatch_tool(
    name: str,
    args: Dict[str, Any],
    case: CaseState,
    latest_message: str = "",
) -> Dict[str, Any]:
    """Run one tool against the shared case state and return its observation."""

    if name == "classify_issue":
        candidates = taxonomy.search(args.get("query", ""))
        return {"candidates": candidates}

    if name == "record_work_order":
        case.summary = args.get("summary") or case.summary
        case.issue_category = args.get("issue_category") or case.issue_category
        case.problem_code = args.get("problem_code") or case.problem_code
        source_urgency = (
            args.get("taxonomy_urgency")
            or args.get("urgency")
            or case.taxonomy_urgency
        )
        if source_urgency in {"EMERGENCY", "URGENT", "ROUTINE"}:
            case.taxonomy_urgency = source_urgency
        case.urgency = _normalize_operational_urgency(
            case.taxonomy_urgency,
            case.safety_flag,
        )
        case.vendor_trade = args.get("vendor_trade") or case.vendor_trade
        if args.get("unit"):
            case.unit = args["unit"]
        case.missing_info = list(args.get("missing_info") or [])
        return {"ok": True, "work_order": case.snapshot()}

    if name == "get_tenant_guidance":
        return {"ok": True, **tenant_guidance.plan_for(latest_message, case)}

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
        if case.status == STATUS_ESCALATED or (
            case.safety_flag and case.urgency == "EMERGENCY"
        ):
            return {
                "ok": False,
                "error": "Emergency or escalated cases cannot be scheduled.",
            }
        result = vendors.find_slots(args.get("trade", case.vendor_trade or ""))
        if result.get("ok"):
            case.offered_slots = result["slots"]
            if case.status not in (STATUS_SCHEDULED, STATUS_ESCALATED, STATUS_RESOLVED):
                case.status = STATUS_AWAITING_TENANT
        return result

    if name == "book_appointment":
        if case.status == STATUS_ESCALATED or (
            case.safety_flag and case.urgency == "EMERGENCY"
        ):
            return {
                "ok": False,
                "error": "Emergency or escalated cases cannot be scheduled.",
            }
        requested = vendors.resolve_slot(args.get("slot_id", ""), case.offered_slots)
        selected = vendors.resolve_explicit_selection(
            latest_message,
            case.offered_slots,
        )
        if requested is None:
            return {
                "ok": False,
                "error": "slot_id was never offered in this case. Offer slots with "
                         "find_vendor_slots and let the tenant choose first.",
            }
        if selected is None or selected.get("slot_id") != requested.get("slot_id"):
            return {
                "ok": False,
                "error": "The latest tenant message did not explicitly and unambiguously select this offered slot.",
            }
        if vendors.slot_is_expired(requested):
            return {
                "ok": False,
                "error": "The selected demo slot has expired. Generate and offer new slots.",
            }
        if case.appointment is not None:
            if case.appointment.get("slot_id") == requested.get("slot_id"):
                return {
                    "ok": True,
                    "appointment": case.appointment,
                    "idempotent": True,
                    "note": "This demo option was already selected; no calendar was reserved and no contractor was contacted.",
                }
            return {
                "ok": False,
                "error": "A different demo option was already selected for this case.",
            }
        case.appointment = requested
        case.status = STATUS_SCHEDULED
        return {
            "ok": True,
            "appointment": requested,
            "note": "Demo appointment selected in case state only; no calendar was reserved and no contractor was contacted.",
        }

    if name == "ask_tenant":
        case.missing_info = list(args.get("missing_fields") or []) or case.missing_info
        if case.status != STATUS_ESCALATED:
            case.status = (
                STATUS_AWAITING_TENANT if case.offered_slots else STATUS_NEEDS_INFO
            )
        return {"ok": True, "status": case.status}

    if name == "escalate_to_manager":
        allowed_flags = {
            "legal_threat",
            "vulnerable_tenant",
            "repeat_unresolved",
            "out_of_scope",
            "tool_conflict",
            "loop_exhausted",
        }
        if not allowed_flags.intersection(case.policy_flags):
            return {
                "ok": False,
                "error": "Manager escalation blocked: no deterministic escalation gate is present. Ask focused questions or route to a simulated vendor instead.",
            }
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

def _context_message(
    case: CaseState,
    safety_result: Dict[str, Any],
    guidance_plan: Dict[str, Any],
) -> Dict[str, str]:
    flag_note = "none"
    if safety_result["flag"]:
        flag_note = (
            f"FLAGGED — {safety_result['reason']}. Treat as urgent and give immediate "
            "containment guidance. This is not a force-escalation result: route the repair "
            "unless another deterministic manager-review gate is present."
        )
    return {
        "role": "system",
        "content": (
            f"Today is {datetime.now().strftime('%A, %Y-%m-%d')}. "
            f"Message channel: {case.channel}.\n"
            f"SAFETY PRE-FILTER: {flag_note}\n"
            "DETERMINISTIC TENANT GUIDANCE (JSON; use these steps/questions and do not "
            f"invent additional DIY work): {json.dumps(guidance_plan, ensure_ascii=False)}\n"
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


def _guided_operational_reply(message: str, case: CaseState) -> str | None:
    """Create a useful non-escalation fallback when the model stops too early."""
    plan = tenant_guidance.plan_for(message, case)
    questions = list(plan.get("questions") or [])[:2]
    safe_steps = list(plan.get("safe_steps") or [])
    trade = plan.get("trade") or case.vendor_trade

    if questions:
        case.missing_info = [question["field"] for question in questions]

    slot_result: Dict[str, Any] = {"ok": False, "slots": []}
    if trade and case.status not in {STATUS_ESCALATED, STATUS_RESOLVED}:
        slot_result = _dispatch_tool(
            "find_vendor_slots",
            {"trade": trade},
            case,
            message,
        )

    if not safe_steps and not questions and not slot_result.get("ok"):
        return None

    issue = plan.get("summary") or case.summary or "maintenance issue"
    issue = (issue or "").strip().rstrip(".")
    if len(issue.split()) > 8 or " is " in issue or " are " in issue:
        issue = (case.problem_code or "maintenance issue").lower()
    location = f" in apartment {case.unit}" if case.unit else ""
    parts = [f"Thanks for reporting the {issue}{location}."]
    if safe_steps:
        parts.append(" ".join(safe_steps))
    if questions:
        parts.append(" ".join(question["question"] for question in questions))
    if slot_result.get("ok"):
        options = "; ".join(
            f"option {slot['option']}: {slot['vendor_name']}, {slot['label']}"
            for slot in slot_result["slots"][:3]
        )
        parts.append(f"I can offer these simulated {trade} windows: {options}.")
        parts.append(
            "Reply with the option number you prefer. This is a demonstration only: "
            "no calendar is reserved and no contractor is contacted."
        )
    elif questions:
        case.status = STATUS_NEEDS_INFO
    return " ".join(parts)


def _routine_reply_is_complete(
    reply: str,
    plan: Dict[str, Any],
    case: CaseState,
) -> bool:
    """Reject polished replies that omit an approved operational requirement."""
    lowered = (reply or "").lower()
    if not lowered or "manager review" in lowered or "escalat" in lowered:
        return False
    if case.unit and case.unit.lower() not in lowered:
        return False
    if len(plan.get("questions") or []) > lowered.count("?"):
        return False
    required_terms = {
        "toilet_clog": ("flush", "chemical"),
        "drain_clog": ("chemical",),
        "no_heat": ("oven", "heater"),
        "electrical_failure": ("unplug", "wiring"),
        "electrical_hazard": ("away", "unplug", "wiring"),
        "water_leak": ("belongings", "electrical"),
        "entry_lock": ("force", "secure"),
    }.get(plan.get("key"), ())
    if not all(term in lowered for term in required_terms):
        return False
    if case.offered_slots:
        if not all(
            f"option {slot['option']}" in lowered
            and slot["vendor_name"].lower() in lowered
            and slot["label"].lower() in lowered
            for slot in case.offered_slots[:3]
        ):
            return False
        if "simulat" not in lowered or not any(
            phrase in lowered
            for phrase in ("no calendar", "not reserved", "isn't reserved", "is not reserved")
        ):
            return False
    return True


def _common_issue_path(
    message: str,
    case: CaseState,
    plan: Dict[str, Any],
) -> Tuple[str, CaseState]:
    """Handle a known, low-risk issue with one compact model call at most."""
    candidates = taxonomy.search(message)
    top = candidates[0] if candidates else {}
    case.add_trace(
        "tool:classify_issue",
        "observe",
        json.dumps(top, ensure_ascii=False)[:240],
    )
    _dispatch_tool(
        "record_work_order",
        {
            "summary": plan.get("summary") or "maintenance issue",
            "issue_category": top.get("category") or "GENERAL",
            "problem_code": top.get("code") or "OTHER / UNCLASSIFIED",
            "urgency": top.get("urgency") or "ROUTINE",
            "taxonomy_urgency": top.get("urgency") or "ROUTINE",
            "vendor_trade": plan.get("trade") or top.get("trade") or "handyman",
            "unit": case.unit,
            "missing_info": [
                question["field"] for question in (plan.get("questions") or [])
            ],
        },
        case,
        message,
    )
    case.add_trace(
        "tool:record_work_order",
        "observe",
        json.dumps(case.snapshot(), ensure_ascii=False)[:240],
    )
    case.add_trace("tool:get_tenant_guidance", "observe", plan.get("key", "common"))
    draft = _guided_operational_reply(message, case)
    if not draft:
        raise RuntimeError("Common-issue policy did not produce an operational response.")
    case.add_trace(
        "tool:find_vendor_slots",
        "observe",
        f"{len(case.offered_slots)} simulated {case.vendor_trade} windows",
    )

    messages = [
        {"role": "system", "content": ROUTINE_RESPONSE_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "tenant_message": message,
                    "approved_draft": draft,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        response = _call_llm(case, SUPERVISOR_MODULE, messages)
        polished = (response.choices[0].message.content or "").strip()
    except Exception as exc:  # the deterministic approved draft remains available
        case.add_trace(
            "supervisor",
            "routine_response_fallback",
            f"{type(exc).__name__}: using deterministic approved draft",
        )
        return draft, case

    if not _routine_reply_is_complete(polished, plan, case):
        case.add_trace(
            "supervisor",
            "routine_response_rejected",
            "polished response omitted or contradicted an approved requirement",
        )
        return draft, case
    case.add_trace("supervisor", "respond", polished[:160])
    return polished, case


def _complete_simulated_selection(
    message: str,
    case: CaseState,
) -> Tuple[str, CaseState] | None:
    """Record an explicitly selected demo option without claiming a real booking."""
    if not case.offered_slots or case.status != STATUS_AWAITING_TENANT:
        return None
    selected = vendors.resolve_explicit_selection(message, case.offered_slots)
    if selected is None:
        return None
    result = _dispatch_tool(
        "book_appointment",
        {"slot_id": selected["slot_id"]},
        case,
        message,
    )
    if not result.get("ok"):
        return None
    case.add_trace(
        "tool:book_appointment",
        "observe",
        f"demo option {selected['option']} selected",
    )
    reply = (
        f"Demo option {selected['option']} is selected: {selected['vendor_name']}, "
        f"{selected['label']}. No calendar was reserved and no contractor or manager "
        "was contacted; this only demonstrates the booking workflow."
    )
    return reply, case


def run_case(message: str, history: List[Dict[str, Any]], case: CaseState) -> Tuple[str, CaseState]:
    """Process one tenant message through the full pipeline. Returns (reply, case)."""

    # ---- 1. Safety Pre-Filter (rule-based, runs before any LLM call) ----
    case.unit = case.unit or _extract_unit(message)
    case.policy_flags = list(
        dict.fromkeys([*case.policy_flags, *_detect_policy_flags(message)])
    )
    safety_result = safety.check(message)
    if safety_result["flag"]:
        case.safety_flag = True
        case.safety_reason = safety_result["reason"]
        case.add_trace("safety_filter", "flag", safety_result["reason"])
    else:
        case.add_trace("safety_filter", "pass", "no emergency keywords matched")

    if safety_result["force_escalate"]:
        return _emergency_path(message, case, safety_result)

    simulated_selection = _complete_simulated_selection(message, case)
    if simulated_selection is not None:
        return simulated_selection

    guidance_plan = tenant_guidance.plan_for(message, case)
    if guidance_plan.get("key") != "generic":
        return _common_issue_path(message, case, guidance_plan)

    # ---- 2. Supervisor agent loop ----
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        _context_message(case, safety_result, guidance_plan),
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
                observation = _dispatch_tool(
                    tc.function.name,
                    args,
                    case,
                    message,
                )
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
    if (
        guidance_plan.get("key") != "generic"
        and case.status in {STATUS_NEEDS_INFO, STATUS_AWAITING_TENANT}
        and case.appointment is None
    ):
        guided_reply = _guided_operational_reply(message, case)
        if guided_reply:
            reply = guided_reply
            case.add_trace(
                "supervisor",
                "guided_response",
                "deterministic safe steps, focused questions, and simulated routing rendered",
            )

    if not case.is_terminal():
        if reply.strip():
            case.status = STATUS_NEEDS_INFO
            case.add_trace(
                "supervisor",
                "model_reply_kept",
                "model produced a grounded tenant reply; state advanced to needs_info",
            )
        else:
            guided_reply = _guided_operational_reply(message, case)
            if guided_reply:
                reply = guided_reply
                case.add_trace(
                    "supervisor",
                    "policy_fallback",
                    "model stopped without a reply; deterministic guidance and routing applied",
                )

    if not reply:
        if not case.is_terminal():
            case.policy_flags.append("loop_exhausted")
            case.status = STATUS_ESCALATED
            case.escalation_reason = "Loop guard: step budget exhausted without a safe operational next state."
        case.add_trace("supervisor", "loop_guard", "step budget exhausted -> manager handoff")
        reply = (
            "Thanks for your message — I couldn't determine a safe next step after the available "
            "checks, so the case is marked for property-manager review. This demo does not send "
            "notifications, so please contact building management directly."
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
