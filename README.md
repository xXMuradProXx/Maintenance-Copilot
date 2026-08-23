# Maintenance Copilot — RAG Agent for Tenant Maintenance Triage

Full-stack AI agent (course final project, *Introduction to Modern AI Agents*)
that turns messy tenant messages ("no heat again since yesterday") into
structured work orders: it classifies the issue against an HPD-style taxonomy,
retrieves landlord obligations from an official housing-guidance corpus (RAG),
and selects a safe next action using an explicit safety pre-filter, autonomy
policy, and loop guard.

For this release, the required `/api/execute` endpoint and root UI deliberately
support one-shot triage only. Multi-turn booking is outside the delivered public
flow until durable server-side case state is implemented. Vendor availability,
appointments, and notifications are demo simulations; they must not be treated
as real reservations or messages to a contractor or manager.

The HPD taxonomy's urgency is retained as source data but is not treated as a
life-safety decision by itself. Only deterministic force-escalation hazards
bypass routing. Known low-risk plumbing reports receive reversible containment
steps, focused questions, and numbered windows from a simulated vendor directory;
unsupported manager escalation and ambiguous/stale demo selections are rejected
in Python.

**Stack:** LLMod/OpenAI-compatible API (chat + embeddings) · Pinecone (vector DB) · FastAPI (Python)
· vanilla HTML/JS frontend · Vercel (serverless deployment).

## Project structure

```
maintenance-copilot/
├── api/
│   ├── index.py            # FastAPI entrypoint (Vercel serverless function)
│   └── lib/                # agent runtime and backend integrations
│       ├── agent.py        # supervisor loop, tools, autonomy policy, loop guard
│       ├── safety.py       # rule-based safety pre-filter (force-escalate/flag)
│       ├── taxonomy.py     # Supabase HPD taxonomy search
│       ├── repositories.py # durable Supabase cases, messages, events, RAG manifest
│       ├── vendors.py      # deterministic demo vendors + generated slots
│       ├── rag.py          # LLMod embeddings + Pinecone retrieval
│       └── state.py        # Shared Case State (work order + decision trace)
├── data/                   # official source documents + grouped HPD taxonomy
├── evaluation/             # recorded live smoke runs and response-quality checks
├── instructions/           # project instructions
├── public/index.html       # response-first assignment UI + structured LLM trace
├── public/model-architecture.png
├── scripts/                # data loaders and connection/retrieval checks
├── supabase/migrations/    # database schema
├── tests/                  # offline API-contract and LLM-trace tests
├── AGENTS.md               # repository rules for future coding agents
├── TODO.md                 # prioritized remaining-work checklist
├── requirements.txt
├── vercel.json             # rewrites /api/* to api/index.py, 300s max duration
└── .env.example
```

## 1. Run locally

```bash
# in the project root
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then paste your LLMod, Pinecone, and Supabase credentials
```

Then prepare the data stores, in this order. A fresh clone will start the app
successfully without these steps, but taxonomy lookups fall back to a small
local table and retrieval returns no citations, so complete them first:

```bash
# 1. Apply the Supabase schema from supabase/migrations/ (SQL editor or CLI)

# 2. Load the HPD complaint taxonomy into Supabase (641 rows)
python scripts/load_taxonomy.py

# 3. Ingest the official PDF corpus into Pinecone + Supabase manifests
python scripts/load_official_sources.py --upload

# 4. Verify retrieval end to end
python scripts/check_rag.py --live
```

Steps 1–3 are one-time. Step 3 is idempotent: unchanged chunks are not
re-embedded, so it is safe to re-run. `PINECONE_NAMESPACE` must be identical
locally and in Vercel, or the deployed app will query an empty namespace.

Start the server:

```bash
uvicorn api.index:app --reload
```

Open http://127.0.0.1:8000 — the frontend, API and interactive docs
(http://127.0.0.1:8000/docs) all run from one server.

## 2. Deploy to Vercel

1. Push the project to a GitHub repository (make sure `.env` is NOT committed —
   it's in `.gitignore`).
2. On https://vercel.com → **Add New… → Project** → import the repo. Framework
   preset: **Other**. No build command needed.
3. In **Settings → Environment Variables**, add the same LLMod, Pinecone,
   Supabase, and model variables used in `.env`. Paste values only — a pasted
   `KEY=value` line makes the variable unusable and fails at request time, not
   at build time.
4. Deploy. Your agent is live at `https://<project>.vercel.app` for anyone with
   the link. `public/` is served statically; `/api/*` hits the Python function.

Environment-variable changes take effect only on a new build, so redeploy after
editing them. `GET /api/health` echoes the resolved model names, Pinecone index
and namespace, and Supabase status; check it before debugging behaviour. When
verifying a deployment, confirm the deployed commit SHA in Vercel matches the
commit you intend to test.

## 3. Assignment API

The four required endpoints are:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/team_info` | Team details |
| `GET` | `/api/agent_info` | Agent description, usage, examples and modules |
| `GET` | `/api/model_architecture` | Architecture diagram as `image/png` |
| `POST` | `/api/execute` | Run one prompt and return `status`, `error`, `response`, and every LLM call in `steps` |

Example:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/execute `
  -ContentType 'application/json' `
  -Body '{"prompt":"The kitchen sink is clogged in apartment 4B."}'
```

Each successful execution is saved to Supabase as a case with user/assistant
messages and ordered `llm_call` events. The older `/api/chat` endpoint remains
available for stateful-client experiments, but the required root UI uses
stateless `/api/execute` calls. The root page keeps the final response visually
primary and places every complete model prompt/response in a collapsible,
copyable trace inspector, which can also export a whole run as JSON. It
preserves the prompt across safe error and retry states; it does not claim to
show structured case data that the assignment response does not expose.

Run the offline assignment-contract suite without calling LLMod, Pinecone, or
Supabase:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite is offline: it mocks provider/database boundaries and verifies the
four required endpoints, exact `/api/execute` response shape, prompt-template
shape, ordered LLM traces, architecture-module consistency, PNG delivery, and
the Vercel-style Python entrypoint.

## 4. Try these demo messages

| Message | Expected agent behavior |
|---|---|
| "The kitchen sink is clogged and water drains very slowly. Apartment 4B." | Fast path: HPD classification, reversible containment steps, two routing questions, three simulated plumber windows. One LLM call. |
| "There has been no heat since yesterday in apartment 12C." | Safety pre-filter flags the hazard; source taxonomy urgency `EMERGENCY` maps to operational `URGENT`, so the case is routed with simulated HVAC windows rather than escalated. |
| "There is black mold spreading across the bathroom ceiling in apartment 5C." | Supervisor loop: classify, retrieve official guidance, record the work order, and reply citing the owner's remediation obligation. |
| "I smell gas in the kitchen of apartment 3F." | Force-escalated by the pre-filter before any model call: immediate safety steps, no appointment offered, marked for manager review. |
| "There is a problem in the bathroom of apartment 7A." | Too little information to classify: asks for details without recording a guessed problem code. |
| "Can you tell me when my rent is due and whether I can get an extension this month?" | Out of scope: declines, escalates for manager review, and redirects to the billing or leasing channel. |

Recorded traces for four of these paths are in
`evaluation/live-smoke-set-2026-08-23.md`.

## Configuration

| Env var                 | Default                                | Purpose                                                                   |
|-------------------------|----------------------------------------|---------------------------------------------------------------------------|
| `LLMOD_BASE_URL`        | —                                      | required LLMod OpenAI-compatible endpoint                                 |
| `LLMOD_API_KEY`         | —                                      | required shared LLMod key                                                 |
| `LLMOD_TIMEOUT_SECONDS` | `45`                                   | per-request timeout                                                       |
| `LLMOD_MAX_RETRIES`     | `2`                                    | SDK retry count                                                           |
| `SUPABASE_URL`          | —                                      | required project URL for taxonomy, cases, audit events, and scheduling    |
| `SUPABASE_SECRET_KEY`   | —                                      | required backend-only secret key; never expose it to the browser          |
| `PINECONE_API_KEY`      | —                                      | required (RAG degrades gracefully without it)                             |
| `PINECONE_INDEX`        | `maintenance-copilot`                  | index name                                                                |
| `PINECONE_NAMESPACE`    | `official-housing-v1`                  | required versioned corpus namespace; set explicitly locally and in Vercel |
| `PINECONE_CLOUD`        | `aws`                                  | optional index-creation setting                                           |
| `PINECONE_REGION`       | `us-east-1`                            | optional index-creation setting                                           |
| `LLMOD_MODEL`           | `MB5R2CF-azure/gpt-5.4-mini`           | supervisor model through LLMod                                            |
| `EMBED_MODEL`           | `MB5R2CF-azure/text-embedding-3-small` | 1536-dim embeddings through LLMod                                         |

Verify the provider before running the app:

```powershell
.\.venv\Scripts\python.exe scripts\check_llmod.py
.\.venv\Scripts\python.exe scripts\check_agent_loop.py
```

## Data sources and provenance

| Source | Type | Size | SHA-256 (prefix) | Retrieved |
|---|---|---|---|---|
| NYC Housing Maintenance Code (Title 27, Ch. 2) | RAG corpus | 76 pages, 490 chunks | `95083768cee702d3` | `<date>` |
| ABCs of Housing (HPD) | RAG corpus | 35 pages, 89 chunks | `d4be06b395b05cb7` | `<date>` |
| HPD Guidelines for Repairs & Maintenance | RAG corpus | 27 pages, 46 chunks | `720348bce5c235e9` | `<date>` |
| HPD Housing Maintenance Code Complaints (grouped) | Structured taxonomy | 641 rows, 11,586,134 complaints | `58b85aada81d5665` | `<date>` |

Corpus totals: 625 chunks, approximately 833,000 characters, in the
`official-housing-v1` namespace. The taxonomy's four source priority labels
(`IMMEDIATE EMERGENCY`, `EMERGENCY`, `HAZARDOUS`, `NON EMERGENCY`) are mapped
once at ingestion to the three-value vocabulary the agent reasons over.

The checked-in PDFs and CSV are local snapshots, not live fetches. Add the
source URL and retrieval date for each before relying on them as current.

## Official PDF ingestion

The RAG corpus consists only of the three official PDFs in `data/`. Validate
page extraction and chunking locally first; this makes no service calls:

```powershell
.\.venv\Scripts\python.exe scripts\load_official_sources.py --dry-run
```

Then upload once to embed all chunks through LLMod and synchronize Pinecone plus
the Supabase `rag_documents`/`rag_chunks` manifests:

```powershell
.\.venv\Scripts\python.exe scripts\load_official_sources.py --upload
```

The upload is idempotent and uses the namespace configured by
`PINECONE_NAMESPACE`. Unchanged chunks are not embedded again; use `--force`
only when you intentionally need to rebuild every vector. Stale chunks are
removed from both Pinecone and Supabase based on the Supabase manifest. After
upload, run the live retrieval check explicitly:

```powershell
.\.venv\Scripts\python.exe scripts\check_rag.py --live
```

Chunking parameters (size 1600, overlap 220, `top_k` 4) are the recorded
baseline. See `TODO.md` for the evaluation-driven workflow intended for changing
them; they should not be adjusted by intuition.

## Current limitations

- The public assignment flow is one prompt per `/api/execute` call; it does not
  yet preserve a case across follow-up prompts. Replies that ask the tenant for
  more detail therefore cannot receive an answer in this deployment.
- `api/lib/vendors.py` returns deterministic demonstration vendors and time
  windows. It does not reserve Supabase slots or contact anyone.
- Common clogged-toilet/drain cases use a compact guarded path: deterministic
  classification, tenant guidance, and simulated availability plus at most one
  LLM call for wording. This prevents routine HPD `EMERGENCY` labels from being
  mistaken for automatic manager escalation.
- Supabase is required for a successful `/api/execute`; Pinecone retrieval can
  degrade gracefully when unavailable, but no retrieved guidance citations are
  available in that fallback mode.
- The portal is the delivered channel. WhatsApp, SMS, and email are conceptual
  channels from the project presentation, not current integrations.
- The ABCs of Housing PDF uses a multi-column layout that the text extractor
  reads linearly, so some retrieved chunks from that document have interleaved
  or broken wording. Retrieval quality is stronger against the Housing
  Maintenance Code. The agent cites sources rather than quoting these chunks
  verbatim to tenants.
- Behaviour is documented from single runs per scenario, not measured success
  rates. Retrieval is similarity-ranked and non-deterministic: the same mold
  prompt cited different in-corpus sources across two runs, both correct.
- The checked-in official PDFs are local snapshots whose freshness still needs
  release verification. Retrieved guidance is source-grounded information, not
  legal advice.
- Emergency guidance has a deterministic fallback, but the app does not contact
  emergency services, building management, tenants, or contractors.

Recorded behaviour for the delivered release is in
`evaluation/live-smoke-set-2026-08-23.md`. `TODO.md` records deliberate
out-of-scope work and the path beyond this release.