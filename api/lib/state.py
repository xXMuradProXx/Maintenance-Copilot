"""Shared Case State.

Every tool reads and writes this one case context (see the architecture
slide: "Shared Case State — every tool reads and writes one case context").

The API is stateless (Vercel serverless): the full case state travels to the
browser with every response and comes back with the next request.
"""

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Terminal / operational states from the "Autonomy boundaries" slide.
STATUS_NEW = "new"
STATUS_NEEDS_INFO = "needs_info"          # waiting for tenant (missing facts)
STATUS_AWAITING_TENANT = "awaiting_tenant"  # waiting for tenant (slot choice)
STATUS_SCHEDULED = "scheduled"
STATUS_ESCALATED = "escalated"
STATUS_RESOLVED = "resolved"

TERMINAL_STATUSES = {
    STATUS_NEEDS_INFO,
    STATUS_AWAITING_TENANT,
    STATUS_SCHEDULED,
    STATUS_ESCALATED,
    STATUS_RESOLVED,
}


def _new_case_id() -> str:
    return "MC-" + uuid.uuid4().hex[:6].upper()


class CaseState(BaseModel):
    """One maintenance case, from messy tenant message to next operational state."""

    case_id: str = Field(default_factory=_new_case_id)
    status: str = STATUS_NEW
    channel: str = "portal"  # whatsapp | sms | email | portal

    # Work-order fields (written by record_work_order)
    unit: Optional[str] = None
    summary: Optional[str] = None
    issue_category: Optional[str] = None
    problem_code: Optional[str] = None
    urgency: Optional[str] = None            # EMERGENCY | URGENT | ROUTINE
    vendor_trade: Optional[str] = None

    # Safety pre-filter
    safety_flag: bool = False
    safety_reason: Optional[str] = None

    # Conversation-driven fields
    missing_info: List[str] = Field(default_factory=list)
    offered_slots: List[Dict[str, Any]] = Field(default_factory=list)
    appointment: Optional[Dict[str, Any]] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    escalation_reason: Optional[str] = None

    # Decision trace ("Evidence travels with the work order")
    trace: List[Dict[str, Any]] = Field(default_factory=list)

    # Assignment-facing audit trail. Unlike ``trace`` (the compact operational
    # log), this contains the complete prompt and response for every LLM call.
    llm_steps: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}  # be forgiving about stale client payloads

    # ------------------------------------------------------------------ helpers

    def add_trace(self, actor: str, action: str, detail: Any = "") -> None:
        """Append one observation to the decision trace (capped at 80 entries)."""
        if len(self.trace) >= 80:
            self.trace = self.trace[-60:]
        self.trace.append(
            {
                "step": len(self.trace) + 1,
                "actor": actor,      # safety_filter | supervisor | tool:<name>
                "action": action,
                "detail": str(detail)[:300],
            }
        )

    def snapshot(self) -> Dict[str, Any]:
        """Compact view of the case for the supervisor's context window."""
        data = self.model_dump(exclude={"trace", "llm_steps", "citations"})
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES
