# Maintenance Copilot - Remaining Work

Last audited: 2026-08-11  
Course deadline: 2026-08-23

This file is the working release checklist. Finish P0 before deployment, then P1. P2 items are useful only after the required assignment flow is reliable.

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
- Thirteen offline API-contract and LLM-trace tests covering all required endpoints, structured failure modes, trace ordering, architecture consistency, and Vercel-style imports.
- Local audit results: all Python files compile; the offline suite passes; taxonomy dry run passes; PDF extraction produces 625 chunks across 138 pages, with 2 pages skipped.

## P0 - Release blockers

### 1. Preserve and clean up the current work
- [ ] Normalize the `api/lib` import strategy so direct `import api.lib.agent` works without first importing `api.index`, or document and test the chosen entrypoint-only strategy.
- [ ] Verify in a Vercel preview build that non-underscored helpers under `api/lib/` are bundled as dependencies and are not exposed or built as unintended functions.

### 2. Make the advertised workflow genuinely end-to-end

- [ ] Decide and document the interaction contract: one-shot triage only, or multi-turn triage plus booking. The current root UI calls stateless `/api/execute`, so a tenant cannot choose a previously offered slot and complete the advertised booking flow.
- [ ] If booking remains in scope, connect the required UI flow to durable server-side case state while preserving the assignment's `/api/execute` request/response contract.
- [ ] Replace deterministic in-memory vendors and generated slots in `api/lib/vendors.py` with the existing Supabase `vendors`, `vendor_slots`, and `appointments` tables, or clearly relabel scheduling as a demo simulation everywhere.
- [ ] Do not claim that a contractor or manager was notified unless a real notification/integration occurred. Return truthful wording for simulated actions.
- [ ] Make booking atomic and concurrency-safe: validate availability, lock/claim the slot, create the appointment, and update the case in one database transaction/RPC.
- [ ] Enforce the explicit-choice rule in code, not only in the prompt. A slot must have been offered before the current model turn and the latest tenant message must unambiguously select it.
- [ ] Enforce terminal-state invariants after the model loop. Do not return `status: ok` with a case still in `new`, or allow scheduling after escalation.
- [ ] Handle timezone, daylight-saving time, weekends/business hours, expired slots, cancellations, duplicate retries, and simultaneous bookings.
- [ ] Either implement the WhatsApp/SMS/email claims from the presentation or clearly state that the delivered app currently supports the portal channel only.

### 3. Verify production data and external services

- [ ] Resolve and verify Supabase connectivity. The 2026-08-11 local health check reported `connected: false` / `migration_applied: false`; determine whether this is network isolation, invalid credentials, or an unapplied migration.
- [ ] Apply `supabase/migrations/001_initial_schema.sql` to the intended project and run `scripts/check_supabase.py` successfully.
- [ ] Load the validated taxonomy with `scripts/load_taxonomy.py`, then make `scripts/check_taxonomy_search.py` pass against Supabase rather than the local fallback.
- [ ] Set `PINECONE_NAMESPACE` explicitly in local and Vercel configuration so corpus versions cannot silently collide.
- [ ] Upload the official corpus once the winning chunking configuration is chosen; confirm Pinecone and the Supabase manifest contain the same document/chunk IDs and hashes.
- [ ] Run `scripts/check_rag.py --live` and verify correct page/file provenance for a broader evaluation set, not only the three current smoke queries.
- [ ] Run the LLMod tool-calling/embedding checks and the agent-loop smoke test, while recording token use and staying within the $13 course budget.
- [ ] Confirm the official documents' versions, authority, and current validity; record retrieval date/source URL/license in document metadata.

### 4. Redesign and verify the UI/UX

- [ ] Do a full visual redesign pass. The current UI needs a clearer hierarchy, more deliberate spacing/typography, and less visual competition between the conversation and the raw trace.
- [ ] Remove or restore the abandoned work-order ticket feature. `public/index.html` still contains ticket CSS and `renderTicket()` calls to missing element IDs, while `/api/execute` does not return `case_state`; none of that UI can currently work.
- [ ] Make the final answer the primary result. Put the technical trace in a secondary, collapsible inspector rather than a dense raw-JSON wall.
- [ ] Render each trace step with separate Module, System Prompt, User Prompt, Response, tool calls, token usage, latency, and error sections; add copy buttons and sensible truncation/expansion for very long values.
- [ ] If structured case data is exposed, show a compact work-order summary with status, category/code, urgency, unit, next action, citations, and appointment state. Otherwise remove all dead case/status UI.
- [ ] Improve loading and failure states: visible elapsed time, disabled/working button state, retry action, validation messages, provider/database-specific safe errors, and preservation of the typed prompt on failure.
- [ ] Make example prompts easier to scan and clearly label normal, ambiguous, urgent, and emergency scenarios.
- [ ] Test responsive layouts at roughly 1440 px, 1024 px, 768 px, and 390 px widths. Avoid squeezed two-column layouts and nested scroll areas on small screens.
- [ ] Test keyboard-only use, focus order, accessible names, color contrast, reduced motion, screen-reader announcements, long/unbroken text, and 200% zoom.
- [ ] Verify the UI states visually: fresh, loading, success with 1 step, success with 6 steps, emergency, validation error, provider timeout, and mobile.
- [ ] Check external font behavior and use robust fallbacks or self-hosted assets so the UI still looks intentional when Google Fonts is blocked or slow.
- [ ] Get one final human visual review before submission; the acceptance criterion is not merely that every required element exists, but that the root page is clear and presentable on first open.

## P1 - Quality, safety, and optimization

### 5. Build an evaluation set before tuning parameters

- [ ] Create a versioned evaluation dataset with representative tenant messages and expected outcomes: taxonomy category/code, urgency, safety action, required/missing fields, vendor trade, expected source/page, next state, and forbidden actions.
- [ ] Cover heat/hot water, plumbing, leaks/mold, electrical, gas/fire/CO, pests, locks/security, appliances, elevators, structural issues, vague reports, multiple simultaneous issues, repeat complaints, legal threats, vulnerable tenants, resolved cases, and out-of-scope prompts.
- [ ] Include paraphrases, misspellings, slang, negation (for example, "I do not smell gas now"), prompt-injection attempts, and at least the languages the product claims to answer.
- [ ] Split the set into tuning and held-out test cases. Do not select parameters on the final held-out set.
- [ ] Define target metrics and release thresholds: safety recall/false-positive rate, taxonomy accuracy/top-k recall, retrieval Recall@K/MRR or nDCG, citation correctness, grounded-answer score, terminal-state accuracy, booking-policy violations, p50/p95 latency, input/output tokens, and estimated cost per case.

### 6. Optimize chunking and ingestion

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

### 7. Optimize retrieval and taxonomy search

Current baseline: RAG `top_k=4`; each returned snippet is capped at 700 characters; case citations are capped at 8. Taxonomy defaults to 5 results and may issue up to 4 Supabase probes, fetching up to 20 rows per probe.

- [ ] Sweep RAG `top_k` values such as 3, 4, 6, and 8 against the evaluation set; pick the smallest value that meets grounded-answer targets.
- [ ] Add and tune a minimum similarity/relevance threshold so unrelated top-k matches are not treated as evidence.
- [ ] Use `authority_rank` in retrieval/ranking and define how law, official guidance, and operational guidance resolve conflicts.
- [ ] Evaluate metadata filters, source balancing, result deduplication, neighboring-chunk expansion, hybrid keyword/vector search, and a lightweight reranker only if the simpler baseline misses targets.
- [ ] Tune how much text enters the supervisor prompt; prefer only the relevant sentences/sections while retaining citation/page context.
- [ ] Evaluate taxonomy top-k, trigram threshold, query expansions, complaint-frequency priors, and the number of database probes. Avoid frequency overpowering a better semantic match.
- [ ] Add explicit confidence/calibration rules for classification and escalate or ask a question below the threshold.
- [ ] Log retrieval candidates, scores, selected evidence, and rejection reasons in a compact audit record without bloating the assignment response.

### 8. Optimize the agent loop, prompts, latency, and cost

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

### 9. Expand automated tests and add CI

- [x] Add an offline standard-library test suite for API contracts and exact LLM tracing; keep live service checks as separate opt-in scripts.
- [x] Cover success, request validation, missing LLMod configuration, provider failure, database failure, PNG delivery, module-name consistency, and serverless-style entrypoint import without live credentials.
- [ ] Unit-test safety regexes, including negation and false positives; taxonomy fallback/scoring; trade normalization; case transitions; slot-selection guards; chunk boundaries/overlap; PDF cleaning; and response serialization.
- [ ] Mock LLMod, Pinecone, and Supabase for deterministic agent-loop tests covering tool errors, malformed tool arguments, empty replies, loop exhaustion, and conflicting tool calls.
- [ ] Add golden end-to-end cases for routine, vague, urgent, force-escalated, resolved, out-of-scope, and multi-issue prompts.
- [ ] Test persistence failure at every stage. Define whether the agent should fail closed, retry, or return a safe response with an explicit audit warning.
- [ ] Add browser end-to-end tests for prompt submission, trace rendering, reset, errors, mobile layout, and multi-turn booking if retained.
- [ ] Add GitHub Actions for lint/format, unit tests, contract tests, static checks, and build/import checks without using live credentials.
- [ ] Run a small, explicitly authorized live smoke suite before release and save a redacted result summary.

### 10. Harden safety, security, and reliability

- [ ] Extract apartment/unit deterministically before the force-emergency path so the emergency reply does not ask for a unit already present in the message.
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

### 11. Documentation and architecture consistency

- [ ] Update README setup order to cover migration, taxonomy load, parameter evaluation, final RAG upload, local verification, and production verification.
- [ ] Document actual limitations: portal-only vs external channels, simulated vs real scheduling/notifications, source freshness, emergency disclaimer, and fallback behavior.
- [ ] Document all tunable parameters with selected values and evidence from the evaluation report.
- [ ] Add data provenance: original URLs, retrieval dates, versions, hashes, transformations, licenses/usage terms, and the reason each source is authoritative.
- [ ] Re-check every claim in README, `/api/agent_info`, the UI, architecture image, and presentation against the code after the scheduling/state decision.
- [ ] Regenerate both SVG and PNG architecture assets from one source after module or flow changes; verify legibility at the endpoint's delivered resolution.
- [ ] Add a short demo script with normal, vague, emergency, and failure cases and the expected trace/state for each.

### 12. Deployment and submission

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
