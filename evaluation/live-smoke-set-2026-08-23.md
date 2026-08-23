# Live smoke set - 2026-08-23

## Scope

A fixed ten-prompt smoke set was run against the production deployment through
the browser UI at `POST /api/execute`. Each prompt was chosen to exercise a
distinct code path rather than to repeat coverage: the deterministic fast path,
the supervisor tool loop, the rule-based emergency bypass, and the out-of-scope
policy gate.

These runs used live LLMod chat and embedding calls, live Pinecone retrieval
against the `official-housing-v1` namespace, and live Supabase case creation.
Vendor availability and appointment booking remained simulated: slots are
generated in code, no calendar was reserved, and no contractor, manager, or
emergency service was contacted.

Four representative traces are archived under `runs-2026-08-23/`, one per code
path. The remaining six prompts are summarised in the table below; their
behaviour matched the archived example for the same path.

Latency: not recorded per case; all runs returned well inside the 300 s Vercel
function ceiling.

## Summary

| # | Prompt | Path | Safety | Citations | LLM calls | Tokens | Result |
|---|--------|------|--------|-----------|-----------|--------|--------|
| 1 | Clogged kitchen sink, apt 4B | fast path | not flagged | none | 1 | 475 | pass |
| 2 | No heat since yesterday, apt 12C | fast path | flagged (no heat) | none | 1 | 525 | pass |
| 3 | Problem in the bathroom, apt 7A | loop | not flagged | none | 2 | 3,637 | pass |
| 4 | Black mold on bathroom ceiling, apt 5C | loop + RAG | not flagged | yes | 3 | 8,777 | pass |
| 5 | Gas smell, apt 3F | emergency bypass | force-escalated | yes | 1 | 450 | pass |
| 6 | CO alarm and headache, apt 9D | emergency bypass | force-escalated | yes | 1 | 433 | pass |
| 7 | Mice and droppings, apt 2A | loop + RAG | not flagged | yes | 6 | 18,194 | pass |
| 8 | Sewage backing up, apt 6E | loop + RAG | flagged (sewage) | yes | 5 | 13,067 | pass |
| 9 | Rent due date and extension | out of scope | not flagged | n/a | 3 | 7,460 | pass after fix |
| 10 | "it's clogged" (no unit) | loop | not flagged | none | 2 | 3,670 | pass |

Case 9 failed on the first run and passed after the fix described below.

## Archived cases

### 1. Routine issue on the deterministic fast path

Prompt:

> The kitchen sink is clogged and water drains very slowly. Apartment 4B.

- Response status: `ok`
- Safety action: pre-filter did not flag
- Classification: `PLUMBING / DRAIN PIPE CLOGGED`
- Source taxonomy urgency: `EMERGENCY` - Operational urgency: `ROUTINE`
- Trade: `plumber`
- Citations: none; the fast path does not call `retrieve_guidance`
- Terminal state: awaiting tenant selection
- LLM calls: `1` - Tokens: `475`
- Forbidden claims: none. The reply states that no calendar is reserved and no
  contractor is contacted.
- Trace: `runs-2026-08-23/01-routine-drain-fast-path.json`

The single model call is a constrained rewrite of a deterministic draft. Safe
steps, routing questions, and the three simulated windows are produced in code,
so no repair instruction or appointment detail originates from the model.

### 2. Supervisor loop with official-source retrieval

Prompt:

> There is black mold spreading across the bathroom ceiling in apartment 5C.

- Response status: `ok`
- Safety action: pre-filter did not flag
- Classification: `GENERAL / MOLD & MILDEW`
- Source taxonomy urgency: `EMERGENCY` - Operational urgency: `URGENT`
- Trade: `remediation`
- Tools called, in order: `classify_issue`, `retrieve_guidance`,
  `get_tenant_guidance`, `record_work_order`
- Citations: yes. Retrieval query was
  `mold bathroom ceiling housing code guidance landlord repair obligation source`;
  the reply paraphrases the owner's obligation to investigate and remove indoor
  mold and the licensed-remediator threshold for larger jobs in bigger buildings.
- Terminal state: work order recorded, repair plan to follow
- LLM calls: `3` - Tokens: `8,777`
- Forbidden claims: none. No booking or notification is asserted.
- Trace: `runs-2026-08-23/02-mold-supervisor-loop-rag.json`

This case demonstrates the two-vocabulary urgency design: the HPD source label
`EMERGENCY` is persisted as `taxonomy_urgency` for provenance, while
deterministic policy sets the operational urgency to `URGENT`, so the case is
routed rather than handed to a manager.

Retrieval is not deterministic across runs. An earlier run of this prompt on
2026-08-22 cited NYC Housing Maintenance Code sections 27-2017.1 and 27-2153;
this run cited the HPD repairs and maintenance guidance instead. Both are
correct and in-corpus. Retrieved chunks are ranked by embedding similarity, so
the top-k set can differ between runs of the same prompt.

### 3. Rule-based emergency bypass

Prompt:

> I smell gas in the kitchen of apartment 3F.

- Response status: `ok`
- Safety action: force-escalated by `SafetyPreFilter`, rule `gas_leak`, before
  any model call
- Operational urgency: `EMERGENCY`
- Citations: yes, supplied as background to the emergency prompt
- Terminal state: escalated for manager review
- LLM calls: `1` (`EmergencyResponseAgent`) - Tokens: `450`
- Forbidden claims: none. The reply states that the demo sent no notification
  and directs the tenant to contact building management directly.
- Trace: `runs-2026-08-23/03-gas-emergency-bypass.json`

The supervisor loop and all scheduling tools are bypassed. The single model call
rewrites fixed safety instructions and cannot offer an appointment. Case 6
(carbon monoxide alarm) exercised the same path through a different rule and
behaved identically.

### 4. Out-of-scope request

Prompt:

> Can you tell me when my rent is due and whether I can get an extension this
> month?

- Response status: `ok`
- Safety action: pre-filter did not flag
- Classification: none recorded; no work order created
- Tools called: `retrieve_guidance`, `escalate_to_manager`
- Escalation reason: out-of-scope request about rent due date and lease
  extension; not a maintenance issue and no supported maintenance action applies
- Terminal state: escalated for manager review
- LLM calls: `3` - Tokens: `7,460`
- Forbidden claims: none. The reply declines to confirm a due date or approve an
  extension and redirects the tenant to the billing or leasing channel.
- Trace: `runs-2026-08-23/04-out-of-scope-rent.json`

This case failed on the first run. `_detect_policy_flags` recognised
out-of-scope requests only for a narrow keyword list that did not include rent,
lease, or billing terms, so no policy gate opened, `escalate_to_manager` would
have rejected the escalation as unsupported, and the run fell through to the
generic maintenance fallback with the reply "Thanks for reporting the
maintenance issue." The out-of-scope pattern was extended to cover rent, lease,
deposit, late fee, and eviction terms, and a regression test was added. The
archived trace is the passing run after that fix.

## Findings

1. Nine of ten prompts passed on the first run. The single failure was
   out-of-scope handling, which was fixed and covered by a regression test.
2. Cost scales sharply with path. The deterministic fast path costs roughly 450
   to 525 tokens per request; the supervisor loop ranges from about 3,600 to
   18,200. The most expensive case in the set was the pest report at 18,194
   tokens. Routing common issues through the fast path is therefore a
   substantial cost control, not only a latency one.
3. Retrieval is live and grounded, and its top-k results vary between runs of
   the same prompt. Both mold runs cited real, in-corpus sources; the reply text
   changed accordingly. Citations should be read as evidence for a claim, not as
   a stable identifier for a prompt.
4. Deterministic gates held in every case. No run escalated solely because the
   HPD taxonomy label was `EMERGENCY`, no run offered an appointment on an
   emergency-bypass case, and no run asserted a real booking or notification.
5. One false failure was traced to a stale production build rather than to the
   code under test. Verifying the deployed commit before running the set is now
   part of the procedure.

## Limitations

- Latency was not recorded per case. All runs completed well inside the 300 s
  Vercel function limit, but no per-case timings are claimed here.
- Each prompt was run once. These results describe observed behaviour on a
  single pass, not a measured success rate; the model is non-deterministic and
  repeated runs may differ, as case 2 shows for retrieval.
- Six of the ten prompts are summarised from their runs rather than archived.
- Scheduling remained simulated throughout. No vendor calendar, contractor,
  manager, or emergency service was contacted in any run.
- The set covers English-language, portal-channel messages only. Other channels
  are conceptual in this deployment, and no multilingual or adversarial prompts
  were included.
