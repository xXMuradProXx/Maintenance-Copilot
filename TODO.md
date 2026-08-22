# Maintenance Copilot - Remaining Work

Last audited: 2026-08-11  
Course deadline: 2026-08-23

This file is the working release checklist. Finish P0 before deployment, then P1. P2 items are useful only after the required assignment flow is reliable.

## Current focus (2026-08-12)

1. **Test the delivered one-shot triage flow end to end.** Expand deterministic safety, agent-loop, API, persistence-failure, and browser coverage before adding another user-facing workflow.
2. **Verify the real integrations deliberately.** Run the smallest authorized Supabase, Pinecone, LLMod, and Vercel smoke checks, record results and cost, and fix failures found by those checks.
3. **Then prototype a simulated booking workflow.** Keep it clearly labeled as a demonstration: no real reservation, contractor contact, manager notification, or durable multi-turn claim until those capabilities actually exist.

Do not let the simulated booking work delay or weaken the assignment-required `/api/execute` flow.

## Current baseline (already present)

- FastAPI app with the four required endpoints: `/api/team_info`, `/api/agent_info`, `/api/model_architecture`, and `/api/execute`.
- LLMod/OpenAI-compatible chat and embedding client.
- Supervisor tool loop, deterministic safety pre-filter, shared case state, loop guard, and complete LLM-call tracing.
- Supabase migration and repositories for taxonomy, cases, messages, events, RAG manifests, vendors, slots, and appointments.
- Pinecone RAG ingestion for three official PDFs, plus an idempotent manifest in Supabase.
- HPD grouped taxonomy loader for 641 rows / 11,586,134 complaints.
- Static root UI with prompt input, Run Agent button, final response, and expandable trace.
- Architecture PNG/SVG, setup documentation, and Vercel configuration with a 300-second function duration.
- Course materials organized under `instructions/`.
- Thirty-seven offline API-contract, package-import, safety-fallback, LLM-trace, public-UI, routine-response, and simulated-booking regression tests covering all required endpoints, structured failure modes, trace ordering, architecture consistency, Vercel-style imports, the root-page interaction contract, common trade routing, escalation gates, and explicit demo slot selection.
- Local audit results: all Python files compile; the offline suite passes; taxonomy dry run passes; PDF extraction produces 625 chunks across 138 pages, with 2 pages skipped.

## P0 - Release blockers

### 1. Preserve and clean up the current work
- [x] Normalize the `api/lib` import strategy so direct `import api.lib.agent` works without first importing `api.index`, or document and test the chosen entrypoint-only strategy.
- [x] Verify in a Vercel preview build that non-underscored helpers under `api/lib/` are bundled as dependencies and are not exposed or built as unintended functions.

### 2. Make the advertised workflow genuinely end-to-end

- [x] Decide and document the interaction contract: one-shot triage only, or multi-turn triage plus booking. The current root UI calls stateless `/api/execute`, so a tenant cannot choose a previously offered slot and complete the advertised booking flow.
- [ ] After the testing milestone below passes, add an optional simulated booking walkthrough while preserving the assignment's stateless `/api/execute` request/response contract.
- [ ] Keep simulated booking state local to the demo or behind a separate clearly named demo endpoint; do not let client-supplied state authorize a real booking or alter another case.
- [ ] Require the tenant to choose a slot that the simulation offered in the immediately preceding step; reject invented, stale, ambiguous, or emergency-case selections deterministically.
- [ ] End the simulation with truthful copy such as “demo appointment selected”; explicitly state that no slot was reserved and nobody was contacted.
- [ ] Add deterministic tests for offer → explicit selection → simulated confirmation, plus emergency, invalid-slot, stale-slot, duplicate-retry, and prompt-injection rejection paths.
- [x] Add the backend simulated vendor workflow: three numbered windows for each supported trade, explicit latest-turn selection, stale/mismatched selection rejection, idempotent duplicate selection, and truthful no-reservation/no-contact confirmation.
- [x] Replace deterministic in-memory vendors and generated slots in `api/lib/vendors.py` with the existing Supabase `vendors`, `vendor_slots`, and `appointments` tables, or clearly relabel scheduling as a demo simulation everywhere.
- [x] Do not claim that a contractor or manager was notified unless a real notification/integration occurred. Return truthful wording for simulated actions.
- [ ] Make booking atomic and concurrency-safe: validate availability, lock/claim the slot, create the appointment, and update the case in one database transaction/RPC.
- [ ] Enforce the explicit-choice rule in code, not only in the prompt. A slot must have been offered before the current model turn and the latest tenant message must unambiguously select it.
- [ ] Enforce terminal-state invariants after the model loop. Do not return `status: ok` with a case still in `new`, or allow scheduling after escalation.
- [ ] Handle timezone, daylight-saving time, weekends/business hours, expired slots, cancellations, duplicate retries, and simultaneous bookings.
- [x] Either implement the WhatsApp/SMS/email claims from the presentation or clearly state that the delivered app currently supports the portal channel only.

### 3. Verify production data and external services

- [x] Resolve and verify Supabase connectivity. The 2026-08-11 local health check reported `connected: false` / `migration_applied: false`; determine whether this is network isolation, invalid credentials, or an unapplied migration.
- [x] Apply `supabase/migrations/001_initial_schema.sql` to the intended project and run `scripts/check_supabase.py` successfully.
- [x] Load the validated taxonomy with `scripts/load_taxonomy.py`, then make `scripts/check_taxonomy_search.py` pass against Supabase rather than the local fallback.
- [x] Set `PINECONE_NAMESPACE` explicitly in local and Vercel configuration so corpus versions cannot silently collide.
- [x] Upload the official corpus once the winning chunking configuration is chosen; confirm Pinecone and the Supabase manifest contain the same document/chunk IDs and hashes.
- [x] Run `scripts/check_rag.py --live` and verify correct page/file provenance for a broader evaluation set, not only the three current smoke queries.
- [x] Run the LLMod tool-calling/embedding checks and the agent-loop smoke test, while recording token use and staying within the $13 course budget.
- [x] Confirm the official documents' versions, authority, and current validity; record retrieval date/source URL/license in document metadata.

### 4. Redesign and verify the UI/UX

- [x] Do a full visual redesign pass. The response-first interface now has a clearer hierarchy, deliberate spacing/typography, and a secondary technical trace.
- [x] Remove or restore the abandoned work-order ticket feature. `public/index.html` no longer contains the dead ticket CSS, missing-element lookups, or unsupported `case_state` path.
- [x] Make the final answer the primary result. The technical trace is a secondary, collapsible inspector rather than a dense raw-JSON wall.
- [x] Render each trace step with separate Module, System Prompt, User Prompt, Response, tool calls, token usage, latency, and error sections; add copy buttons and sensible truncation/expansion for very long values.
- [x] If structured case data is exposed, show a compact work-order summary with status, category/code, urgency, unit, next action, citations, and appointment state. The assignment response does not expose structured case data, so all dead case/status UI was removed.
- [x] Improve loading and failure states: visible elapsed time, disabled/working button state, retry action, validation messages, provider/database-specific safe errors, and preservation of the typed prompt on failure.
- [x] Make example prompts easier to scan and clearly label normal, ambiguous, urgent, and emergency scenarios.
- [ ] Test responsive layouts at roughly 1440 px, 1024 px, 768 px, and 390 px widths. Avoid squeezed two-column layouts and nested scroll areas on small screens.
- [ ] Test keyboard-only use, focus order, accessible names, color contrast, reduced motion, screen-reader announcements, long/unbroken text, and 200% zoom.
- [ ] Verify the UI states visually: fresh, loading, success with 1 step, success with 6 steps, emergency, validation error, provider timeout, and mobile.
- [x] Check external font behavior and use robust fallbacks or self-hosted assets so the UI still looks intentional when Google Fonts is blocked or slow. The public page now uses a system-only font stack and makes no external font request.
- [x] Get one human visual review of the redesign. User review on 2026-08-12: “UI looks pretty nice.” Repeat a final review after browser-state testing and any simulated-booking UI changes.

### 5. Prove the current flow works before expanding it

- [ ] Add focused unit tests for safety regexes (positive, negative, negated, misspelled, multilingual, and adversarial), taxonomy fallback/scoring, case transitions, and terminal-state enforcement.
- [ ] Add mocked agent-loop tests for routine, ambiguous, urgent, force-emergency, resolved, out-of-scope, multiple-issue, malformed-tool, tool-error, empty-reply, conflict, and loop-exhaustion paths.
- [ ] Test persistence failure at case creation, message append, event append, and case update; define and assert the safe public result at each boundary.
- [ ] Add browser end-to-end tests for prompt submission, validation, loading, success with 1 and 6 steps, emergency, timeout/error retry, copy controls, long/unbroken content, and mobile layout.
- [ ] Verify keyboard-only navigation, focus order/visibility, accessible names, live announcements, reduced motion, contrast, 200% zoom, and widths near 1440, 1024, 768, and 390 px.
- [ ] Create a fixed smoke dataset and record expected response status, safety action, taxonomy result, citations, terminal state, step count, latency, and forbidden claims for every case.
- [ ] Run the full offline suite and production-like import/routing checks in CI without live credentials.
- [ ] Only after offline checks pass, run one small explicitly authorized live smoke set; record redacted Supabase/Pinecone/LLMod results, token use, latency, and estimated cost.
- [x] Run and record the exact clogged-toilet response-quality smoke check after offline policy tests. Final result: one LLMod call, 518 tokens, useful guidance/questions/windows, no unsupported escalation; see `evaluation/response-quality-smoke-2026-08-12.md`. This is one scenario, not the full live smoke set above.
- [ ] Run the same smoke set against a Vercel preview and verify the root UI plus all four required endpoints before production deployment.

## P1 - Quality, safety, and optimization

### 6. Build an evaluation set before tuning parameters

- [ ] Create a versioned evaluation dataset with representative tenant messages and expected outcomes: taxonomy category/code, urgency, safety action, required/missing fields, vendor trade, expected source/page, next state, and forbidden actions.
- [ ] Cover heat/hot water, plumbing, leaks/mold, electrical, gas/fire/CO, pests, locks/security, appliances, elevators, structural issues, vague reports, multiple simultaneous issues, repeat complaints, legal threats, vulnerable tenants, resolved cases, and out-of-scope prompts.
- [ ] Include paraphrases, misspellings, slang, negation (for example, "I do not smell gas now"), prompt-injection attempts, and at least the languages the product claims to answer.
- [ ] Split the set into tuning and held-out test cases. Do not select parameters on the final held-out set.
- [ ] Define target metrics and release thresholds: safety recall/false-positive rate, taxonomy accuracy/top-k recall, retrieval Recall@K/MRR or nDCG, citation correctness, grounded-answer score, terminal-state accuracy, booking-policy violations, p50/p95 latency, input/output tokens, and estimated cost per case.

### 7. Optimize chunking and ingestion

Current baseline: character-based, page-bounded chunks; target 1,600 characters; 220-character overlap; pages under 40 characters skipped; 625 total chunks. A dry run currently takes about 81 seconds locally.

- [ ] Make chunking parameters configurable by CLI/env and store the complete configuration/version in every document manifest and Pinecone namespace.
- [ ] Compare token-aware or sentence/section-aware chunk sizes (for example 256, 384, 512, and 768 tokens) instead of optimizing only character counts.
- [ ] Compare overlap ratios around 0%, 10%, 15%, and 20%; measure duplicate retrieval and context waste as well as recall.
- [ ] Compare strict page boundaries with section-aware chunks that may join short adjacent page fragments while preserving exact page ranges.
- [ ] Merge or discard tiny/noisy chunks; detect repeated headers, footers, page numbers, tables of contents, and extraction artifacts.
- [ ] Preserve legal section numbers, headings, tables, bullets, page ranges, source authority, and version metadata in each chunk.
- [ ] Add cached extracted text/chunk manifests so repeated parameter experiments do not re-extract all PDFs for roughly 81 seconds each.
- [ ] Add progress reporting and per-document timing to ingestion; validate skipped pages visually before accepting them.
- [ ] Run each chunking candidate in a separate versioned namespace, evaluate it on the fixed query set, and record recall, grounding, latency, vector count, embedding tokens, and dollar cost.
- [ ] Select and document the winning configuration, delete obsolete experiment namespaces deliberately, and re-run the full ingestion consistency check.

### 8. Optimize retrieval and taxonomy search

Current baseline: RAG `top_k=4`; each returned snippet is capped at 700 characters; case citations are capped at 8. Taxonomy defaults to 5 results and may issue up to 4 Supabase probes, fetching up to 20 rows per probe.

- [ ] Sweep RAG `top_k` values such as 3, 4, 6, and 8 against the evaluation set; pick the smallest value that meets grounded-answer targets.
- [ ] Add and tune a minimum similarity/relevance threshold so unrelated top-k matches are not treated as evidence.
- [ ] Use `authority_rank` in retrieval/ranking and define how law, official guidance, and operational guidance resolve conflicts.
- [ ] Evaluate metadata filters, source balancing, result deduplication, neighboring-chunk expansion, hybrid keyword/vector search, and a lightweight reranker only if the simpler baseline misses targets.
- [ ] Tune how much text enters the supervisor prompt; prefer only the relevant sentences/sections while retaining citation/page context.
- [ ] Evaluate taxonomy top-k, trigram threshold, query expansions, complaint-frequency priors, and the number of database probes. Avoid frequency overpowering a better semantic match.
- [ ] Add explicit confidence/calibration rules for classification and escalate or ask a question below the threshold.
- [ ] Log retrieval candidates, scores, selected evidence, and rejection reasons in a compact audit record without bloating the assignment response.

### 9. Optimize the agent loop, prompts, latency, and cost

Current baseline: up to 6 supervisor iterations, 12 prior chat messages, 4,000 characters per history message, 45-second provider timeout, 2 SDK retries, and no explicit output-token cap or deterministic sampling setting.

- [ ] Measure actual calls, tokens, latency, and cost per scenario. Add budget accounting and a hard test-run budget so evaluation cannot exhaust the shared $13 key.
- [ ] Tune `MAX_STEPS` using successful-path distributions; aim for the fewest calls that still complete classification, evidence retrieval, and a valid next state.
- [ ] Reduce repeated prompt/tool-schema/context tokens between loop iterations where the API/provider permits it.
- [ ] Tune history length and per-message truncation using multi-turn tests; summarize older state rather than sending redundant conversation plus case state.
- [ ] Set and test an explicit output-token limit and deterministic/low-variance sampling parameters if LLMod supports them.
- [ ] Tune timeout and retry policy against Vercel's 300-second ceiling, including worst-case backoff. Fail early enough to return a structured error.
- [ ] Avoid unnecessary guidance embeddings when the taxonomy/safety result already establishes the next safe action, but never skip evidence required for legal or policy claims.
- [ ] Add request-level timing for safety, taxonomy, embeddings, Pinecone, each LLM call, Supabase persistence, and total execution.
- [ ] Make the chosen parameters configuration-driven, validated, documented, and included in an experiment report rather than left as unexplained constants.

### 10. Expand automated tests and add CI

- [x] Add an offline standard-library test suite for API contracts and exact LLM tracing; keep live service checks as separate opt-in scripts.
- [x] Cover success, request validation, missing LLMod configuration, provider failure, database failure, PNG delivery, module-name consistency, and serverless-style entrypoint import without live credentials.
- [ ] Complete the P0 functional-testing milestone above; keep this section for deeper coverage such as chunk boundaries/overlap, PDF cleaning, trade normalization, response serialization, and longer-running evaluation cases.
- [ ] Extend CI with lint/format, static checks, ingestion dry-run checks where affordable, and artifact retention for redacted test reports.
- [ ] Add simulated-booking browser coverage only after the one-shot triage browser suite is stable.

### 11. Harden safety, security, and reliability

- [x] Extract apartment/unit deterministically before the force-emergency path so the emergency reply does not ask for a unit already present in the message.
- [ ] Validate all state transitions and sensitive actions outside the LLM. Treat the model as a planner, not the authority for safety and booking policy.
- [ ] Stop trusting arbitrary client-supplied `/api/chat.case_state`; load authoritative state by opaque case ID or validate/sign client state.
- [ ] Add prompt-injection and data-exfiltration tests. Never let tenant text override system policy or expose other cases, prompts, secrets, or internal data.
- [ ] Sanitize public errors. Log detailed provider/database exceptions server-side with a correlation ID instead of returning raw exception messages.
- [ ] Protect the unauthenticated public endpoint from budget abuse with rate limits, request quotas, bounded concurrency, body-size limits, and monitoring while keeping the required GUI immediately accessible.
- [ ] Review permissive CORS and restrict it to what the grader/root UI actually needs.
- [ ] Define privacy/retention rules for tenant messages, unit numbers, traces, and appointments; add deletion/retention jobs if real personal data will be accepted.
- [ ] Persist non-LLM tool actions and safety decisions as ordered events, or document why the compact decision trace is sufficient for the project audit.
- [ ] Add idempotency keys/retry handling so Vercel/client retries cannot duplicate cases, messages, appointments, or notifications.
- [ ] Verify graceful behavior when LLMod, Pinecone, or Supabase is slow/unavailable and ensure emergency guidance always returns promptly.

## P2 - Documentation, deployment, and presentation polish

### 12. Documentation and architecture consistency

- [ ] Update README setup order to cover migration, taxonomy load, parameter evaluation, final RAG upload, local verification, and production verification.
- [ ] Document actual limitations: portal-only vs external channels, simulated vs real scheduling/notifications, source freshness, emergency disclaimer, and fallback behavior.
- [ ] Document all tunable parameters with selected values and evidence from the evaluation report.
- [ ] Add data provenance: original URLs, retrieval dates, versions, hashes, transformations, licenses/usage terms, and the reason each source is authoritative.
- [ ] Re-check every claim in README, `/api/agent_info`, the UI, architecture image, and presentation against the code after the scheduling/state decision.
- [ ] Regenerate both SVG and PNG architecture assets from one source after module or flow changes; verify legibility at the endpoint's delivered resolution.
- [ ] Add a short demo script with normal, vague, emergency, and failure cases and the expected trace/state for each.

### 13. Deployment and submission

- [ ] Link/configure the Vercel project and add the final LLMod, Pinecone, Supabase, model, namespace, timeout, and parameter environment variables.
- [ ] Check the Vercel Python bundle size/cold start. Exclude ingestion-only PDFs/scripts from the serverless function bundle if necessary without removing required source provenance from Git.
- [ ] Deploy a preview, then run all four required endpoints and the root UI against the preview URL.
- [ ] Verify no authentication gate, root-page redirect, CORS issue, static-asset failure, case-sensitive import problem, or serverless write assumption appears in production.
- [ ] Load-test representative executions and confirm p95 latency and worst-case retry paths stay well under 300 seconds.
- [ ] Inspect Vercel logs for cold-start/import/provider/database failures and ensure logs do not contain secrets or excessive tenant data.
- [ ] Promote to production, run the final smoke/evaluation subset, and save the timestamped results and deployed commit SHA.
- [ ] Push a clean GitHub repository, confirm all required untracked files are included, and verify a fresh clone can install and run from README alone.
- [ ] Submit the production Vercel URL and GitHub URL in the exact requested format, and keep the deployment/account active until grading is complete.

## Final definition of done

- [ ] All four required endpoints pass automated contract tests locally and in production.
- [ ] The root UI is visually approved, responsive, accessible, and exposes the complete readable LLM trace.
- [ ] Every advertised action is real and durable, or is explicitly labeled as simulated/not supported.
- [ ] Safety and booking invariants are enforced in code and pass adversarial tests.
- [ ] Taxonomy and RAG evaluation meet documented thresholds on the held-out set with citations and provenance intact.
- [ ] Parameter choices are backed by recorded quality/latency/cost results and remain within the $13 budget.
- [ ] Supabase, Pinecone, LLMod, and Vercel smoke checks pass on the deployed commit.
- [ ] Git is clean, secrets are absent, documentation matches behavior, and submission links are ready.
