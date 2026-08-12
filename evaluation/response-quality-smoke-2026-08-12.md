# Response-quality smoke check - 2026-08-12

## Scope

One live LLMod scenario was used to verify the reported over-escalation bug after
offline policy tests passed. The command called `run_case` directly, so it did
not create or update a Supabase case. Vendor availability remained simulated.

## Scenario

Prompt:

> Apartment 3A. Toilet is clogged.

Expected behavior:

- do not escalate solely because the HPD taxonomy priority is `EMERGENCY`;
- give reversible, low-risk containment guidance;
- ask whether the bowl is overflowing/rising and whether another toilet works;
- route to a plumber and offer clearly labeled simulated windows;
- state that no real calendar or contractor was contacted.

## Final live result

- Operational status: `awaiting_tenant`
- Classification: `PLUMBING / DRAIN PIPE CLOGGED`
- Source taxonomy urgency: `EMERGENCY`
- Operational urgency: `URGENT`
- Trade: `plumber`
- LLM calls: `1`
- Total tokens reported by LLMod: `518`

Response:

> Thanks for reporting the clogged toilet in apartment 3A. Do not flush it again while the bowl is high. If the water starts rising and the shutoff valve behind the toilet is easy to reach, turn it clockwise without forcing it. Avoid chemical drain cleaners, which can create a splash hazard and complicate the repair. Is the bowl overflowing or is the water still rising? Is there another working toilet in the apartment? I can offer these simulated plumber windows: option 1: Rapid Rooter Plumbing, Thursday, Aug 13, 10:00–12:00; option 2: BlueLine Plumbing & Heating, Thursday, Aug 13, 14:00–16:00; option 3: Rapid Rooter Plumbing, Friday, Aug 14, 9:00–11:00. Reply with the option number you prefer. This is a demonstration only: no calendar is reserved and no contractor is contacted.

Result: passed the expected behavior above.

## Optimization note

The first live iteration reached the correct guarded response but consumed six
LLM calls and 15,148 tokens. The common plumbing path was then changed to do
classification, safe guidance, focused questions, and simulated slot generation
deterministically, with at most one compact LLM call for tenant-facing wording.
The final live result used 518 tokens, a 96.6% reduction from that first
iteration. Dollar cost is not recorded because no verified LLMod price was
available in the runtime.

## Remaining limitation

The backend can validate and record an explicit simulated option selection on a
subsequent stateful `/api/chat` turn. The required root UI still uses stateless
`/api/execute`, so the tenant cannot yet complete that second turn from the root
page. No real slot is held or booked.
