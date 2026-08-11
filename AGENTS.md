# AGENTS.md

These instructions apply to the entire repository.

## Project mission

Maintenance Copilot is a course project that turns unstructured tenant maintenance messages into safe, grounded work orders and a clear next operational state. The system combines:

- a deterministic safety pre-filter;
- an LLMod-hosted supervisor model with tool calling;
- the NYC HPD maintenance taxonomy in Supabase;
- official housing documents retrieved through Pinecone RAG;
- shared case state, persistence, scheduling, and an auditable LLM trace;
- a public root UI and four assignment-required API endpoints.

The course deadline is 2026-08-23. The shared LLMod budget is $13 total, so unnecessary live model and embedding calls are unacceptable.

## Read before changing anything

Use these sources in this order:

1. `instructions/Project.pdf` - authoritative course requirements and API/UI contract.
2. `instructions/Assignment 2_ Find Data Sources for your Al Agents.pdf` - approved data-source rationale and provenance.
3. `instructions/Batch1_4_Aviv_Murad.pdf` - intended product story, architecture, and autonomy boundaries.
4. `TODO.md` - audited remaining work, priorities, current baselines, and release criteria.
5. `README.md` and `supabase/README.md` - setup and operating procedures.
6. `public/model-architecture.svg` / `.png` - public architecture and module names.
7. The implementation and tests - actual behavior.

If documentation and code conflict, do not silently choose one. Preserve the assignment contract, identify the mismatch, and update the code and documentation together.

## Current repository state

- The working tree contains a large uncommitted migration from `api/_lib/` to `api/lib/`, replacement of the old Markdown corpus with official PDFs, new Supabase/RAG scripts, and a rewritten UI/API.
- Treat all existing modifications and untracked project files as user work. Do not reset, discard, or overwrite them.
- `TODO.md` was produced from a repository and requirements audit on 2026-08-11. Work P0 in order unless the user gives a different priority.
- P0.2 is implemented: strict response models enforce the assignment API shapes, public module names are centralized, and 13 offline contract/trace tests pass.
- `LLMOD_API_KEY` is the only supported LLM credential variable.
- The `api/lib` migration works through `api.index` and the Vercel-style entrypoint test. Direct `import api.lib.agent` still fails because internal imports use top-level `lib`; treat this as an open packaging cleanup item, not a reason to restore deleted code casually.
- The current UI has abandoned work-order ticket CSS/JavaScript whose required DOM nodes and API state are absent. Do not build new behavior on that dead path without deliberately restoring or removing it.
- The current required UI path uses stateless `/api/execute`; the optional `/api/chat` path carries client-provided state. The advertised multi-turn booking flow is therefore not complete through the root UI.
- `api/lib/vendors.py` still uses deterministic demo vendors/slots even though the Supabase schema contains production-style scheduling tables.

## Language and architecture decision

Keep the backend in Python/FastAPI for this release. Do not rewrite it in TypeScript unless the user explicitly requests a migration after reviewing scope, tests, and deployment risk.

Reasons:

- the agent, ingestion, PDF parsing, Supabase repositories, Pinecone integration, scripts, and deployment entrypoint already exist in Python;
- Python has the strongest fit for the current PDF/RAG/evaluation work;
- the main blockers are product-state, UI, testing, service verification, and evaluation problems, not Python limitations;
- a rewrite close to the deadline would consume time and create contract regressions without improving model quality.

TypeScript is acceptable as an incremental frontend choice if the UI grows beyond a small static page and the user approves adding a build system. If introduced, keep FastAPI as the API, generate or share a documented API schema, and migrate one surface at a time. Do not run two independent business-logic implementations.

## Non-negotiable assignment contract

The deployed app must expose these exact endpoints:

- `GET /api/team_info`
- `GET /api/agent_info`
- `GET /api/model_architecture`
- `POST /api/execute`

`POST /api/execute` accepts:

```json
{
  "prompt": "User request here"
}
```

Its top-level response must contain exactly:

```json
{
  "status": "ok",
  "error": null,
  "response": "...",
  "steps": []
}
```

On error, `status` is `error`, `error` is human-readable, `response` is `null`, and `steps` remains an array.

Every LLM call must appear once, in chronological order, in `steps`. Each step must include:

- `module` - exactly consistent with the architecture diagram;
- `prompt.system_prompt` and `prompt.user_prompt`;
- the complete JSON-safe model `response`.

The root URL must immediately show a public UI with no authentication gate. It must provide a textarea, a visible `Run Agent` action that invokes `/api/execute`, the final response, and the full readable LLM trace.

`/api/agent_info.prompt_template` must remain an object containing at least `template`. Keep the regression test for this exact shape.

## Module naming

Names exposed in traces, `/api/agent_info`, descriptions, and the architecture diagram must remain synchronized. Current public names include:

- `SafetyPreFilter`
- `SupervisorAgent`
- `EmergencyResponseAgent`
- `TaxonomySearch`
- `GuidanceRetriever`
- `SchedulingTools`
- `SharedCaseState`
- `SupabaseAuditStore`

Only actual LLM calls belong in assignment `steps`. Deterministic tools and safety actions belong in the operational/audit trace unless the contract is intentionally extended without changing the required top-level shape.

## Safety and state invariants

These rules must be enforced in Python, not trusted to prompt compliance alone:

- Force-escalation hazards bypass normal scheduling and always return immediate safety guidance.
- Emergency cases cannot be scheduled.
- A tenant-selected slot must have been offered before the current model turn and must be explicitly selected in the latest tenant message.
- Booking must be atomic, idempotent, timezone-aware, and concurrency-safe.
- Do not claim a manager, contractor, tenant, or emergency service was notified unless an integration actually performed that action.
- A successful execution must reach a valid operational next state; a free-form model reply must not leave the case silently in `new`.
- Tool conflicts, low confidence, policy conflicts, legal threats, vulnerable tenants, repeat unresolved complaints, and exhausted loops should fail safe or escalate.
- Never let client-supplied case state authorize bookings, suppress safety flags, or expose another case.
- Keep emergency fallback text deterministic and available when LLMod, Pinecone, or Supabase fails.

When changing safety rules, add positive, negative, negated, misspelled, multilingual, and adversarial tests. False positives such as negated hazard language matter as much as obvious matches.

## Data and RAG rules

Use only approved, traceable sources. The current corpus is:

- `data/newyorkcity-ny-1.pdf`
- `data/abcs-of-housing.pdf`
- `data/hpd-guidelines-repairs-maintenance.pdf`
- `data/Housing_Maintenance_Code_Complaints_and_Problems_grouped.csv`

Do not reintroduce the removed handwritten `data/housing_guidance/` files as authoritative evidence.

Preserve source title, issuing authority, file name, version, content hash, section, and page range through extraction, Pinecone metadata, Supabase manifests, citations, and audit records. Do not make a legal/policy claim from an unrelated low-score result merely because Pinecone returned a top-k match.

Current ingestion baseline:

- target chunk size: 1,600 characters;
- overlap: 220 characters;
- page-bounded chunks;
- minimum usable page text: 40 characters;
- dry-run result: 625 chunks across the three PDFs, with 2 pages skipped;
- RAG query `top_k`: 4;
- returned snippet cap: 700 characters.

Do not change chunk size, overlap, top-k, thresholds, history limits, or loop limits by intuition alone. Follow the evaluation workflow in `TODO.md`: fixed dataset, tuning/held-out split, versioned namespace, quality metrics, latency, token use, and cost. Record the winning parameters and rationale.

Ingestion must remain local-only by default. Network writes require the explicit `--upload` flag. Preserve idempotency and content-hash checks. Never use `--force` casually.

## External services and budget

Required services are LLMod, Supabase, Pinecone, and Vercel.

- Never print or commit `.env`, API keys, Supabase service-role secrets, tokens, or raw authorization headers.
- The browser must never receive `SUPABASE_SECRET_KEY` or other backend credentials.
- Avoid live LLM/embedding calls unless they are necessary for the task. Tell the user before running a broad or potentially costly evaluation/upload.
- Use mocked tests for normal development. Keep live checks small, deliberate, and clearly separated.
- Do not rotate keys, apply database migrations, upload/rebuild indexes, delete namespaces, deploy, or send notifications unless the user has authorized that external change.
- Public health and error responses must expose configuration status only, never credentials or raw sensitive exception details.
- The production path must remain comfortably below Vercel's 300-second maximum, including retries and persistence.

Configuration naming must be consistent across code, `.env.example`, README, and Vercel. `LLMOD_API_KEY` is the only supported LLMod credential variable; do not add or document an alternative fallback.

## UI expectations

The user explicitly reported that the UI looked terrible. Treat UI work as a product redesign and verification task, not a cosmetic afterthought.

- Establish a clear hierarchy: prompt and final answer first, technical trace second.
- Use a collapsible, readable trace inspector instead of an undifferentiated raw JSON wall.
- Remove dead CSS/JavaScript/DOM paths.
- Preserve complete trace data even when the visual presentation truncates it behind an expansion control.
- Keep all tenant/model text XSS-safe. Prefer `textContent`; never inject untrusted HTML.
- Provide useful loading, timeout, validation, retry, and failure states.
- Test long prompts/responses and 1-6 trace steps at desktop, tablet, and mobile widths.
- Verify keyboard navigation, focus visibility/order, accessible names, contrast, reduced motion, screen-reader announcements, and 200% zoom.
- Do not consider UI work complete until the latest implementation has been inspected in a real browser in fresh, loading, success, emergency, error, long-trace, and mobile states.

If a frontend framework is introduced, justify its bundle/build complexity. A framework is not a substitute for a coherent information hierarchy and visual QA.

## Python conventions

- Support the existing Python version/environment unless the deployment target requires a documented change.
- Keep the Vercel ASGI entrypoint at `api/index.py`.
- Keep backend modules under `api/lib/`; do not recreate `api/_lib/`.
- Prefer typed Pydantic models and small repository/service boundaries.
- Keep external clients lazy or cached where appropriate to reduce serverless cold starts.
- Keep safety-critical transitions deterministic and independently testable.
- Return public-safe error messages and retain detailed exceptions only in controlled server logs.
- Avoid broad `except Exception` unless the boundary must degrade safely; document the fallback and test it.
- Do not add dependencies when the standard library or an existing dependency is sufficient.
- Keep import behavior valid both under `uvicorn api.index:app` and Vercel's function bundle.

## Database and scheduling conventions

- Apply schema changes through new ordered SQL migrations; do not rewrite an already-applied migration unless the project is explicitly being reset.
- Enable and review RLS for every exposed table. The public browser must not access service-role data directly.
- Use repositories/RPCs for durable operations and translate provider errors into domain-safe exceptions.
- Scheduling mutations require a database transaction/RPC and idempotency strategy.
- Demo seed data must be clearly labeled and must not be confused with real vendor availability or communication.
- Store timestamps in UTC and render in the intended property timezone.

## Testing and validation

Run the smallest relevant checks during development, then the broader local suite before handoff.

Safe local checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q api scripts
.\.venv\Scripts\python.exe scripts\load_taxonomy.py --dry-run
.\.venv\Scripts\python.exe scripts\load_official_sources.py --dry-run
git diff --check
```

The PDF dry run takes roughly 80 seconds in the current environment. Do not rerun it after an unrelated UI-only edit.

Read-only/live integration checks, only when relevant and configured:

```powershell
.\.venv\Scripts\python.exe scripts\check_supabase.py
.\.venv\Scripts\python.exe scripts\check_taxonomy_search.py
.\.venv\Scripts\python.exe scripts\check_llmod.py
.\.venv\Scripts\python.exe scripts\check_agent_loop.py
.\.venv\Scripts\python.exe scripts\check_rag.py --live
```

`check_llmod.py`, `check_agent_loop.py`, and `check_rag.py --live` can consume the shared LLMod budget. Do not run them repeatedly.

The current offline suite covers the four required endpoint contracts, success
and structured error responses, exact LLM trace recording, architecture-module
consistency, PNG delivery, and a Vercel-style entrypoint import.

When adding tests:

- keep unit and contract tests offline and deterministic;
- mock LLMod, Pinecone, and Supabase by default;
- mark live tests clearly and exclude them from ordinary CI;
- test both success and structured failure contracts;
- add a regression test for every bug fixed;
- include production-like Vercel import/routing checks.

## Git and file hygiene

- Inspect `git status` before and after edits.
- Preserve unrelated user changes in this dirty working tree.
- Do not use `git reset --hard`, destructive checkout, broad deletion, or history rewriting.
- Do not commit `.env`, caches, logs, temporary PDF renders, experiment output, `.vercel/`, or local virtual environments.
- Use `apply_patch` for intentional source/documentation edits.
- Keep generated architecture PNG and its SVG source synchronized.
- Before committing, review staged files, run `git diff --check`, and scan for secrets.
- Do not commit, push, open a PR, deploy, or modify external data unless the user asks.

## Documentation requirements

Update documentation in the same change when behavior, configuration, endpoints, module names, data sources, parameters, or limitations change.

Be precise about what the system actually does. In particular:

- distinguish portal support from conceptual WhatsApp/SMS/email channels;
- distinguish simulated scheduling/notification from real actions;
- state when Pinecone or Supabase fallback changes behavior;
- do not call advice legally authoritative beyond its cited official source;
- keep README, `/api/agent_info`, UI copy, architecture assets, and presentation claims aligned.

## Handoff checklist

Before saying a change is complete:

1. Re-read the relevant P0/P1 item in `TODO.md`.
2. Confirm the assignment contract is unchanged or deliberately repaired.
3. Run proportionate local tests and report exactly what was and was not run.
4. Inspect the resulting UI visually if UI code changed.
5. Check `git status` and mention remaining unrelated/uncommitted work.
6. Update `TODO.md` only for work genuinely completed and verified.
7. Do not claim live service, notification, deployment, or visual verification that did not occur.
