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
   Supabase, and model variables used in `.env`.
4. Deploy. Your agent is live at `https://<project>.vercel.app` for anyone with
   the link. `public/` is served statically; `/api/*` hits the Python function.

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
copyable trace inspector. It also preserves the prompt across safe error and
retry states; it does not claim to show structured case data that the assignment
response does not expose.

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
| "The kitchen sink is clogged and water drains very slowly. Apt 4B." | Uses the official HPD plumbing classification and mapped urgency |
| "No heat again since yesterday, apartment 12C" | Safety flag + RAG heat-season rules → EMERGENCY → **Escalated** |
| "I smell gas in my kitchen!!" | Force-escalate: bypasses the LLM loop, immediate 911/utility safety steps |
| "bathroom problem" | Missing facts → asks 1–2 questions → **Waiting for tenant info** |

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

## Official PDF ingestion

The RAG corpus consists only of the three official PDFs in `data/`. Validate
page extraction and chunking locally first; this makes no service calls:

```powershell
.\.venv\Scripts\python.exe scripts\load_official_sources.py --dry-run
```

Do not upload immediately after a dry run. First evaluate candidate chunking
settings on the fixed tuning set, choose a versioned namespace, and record the
winning configuration. Then deliberately upload that corpus once to embed all
chunks through LLMod and synchronize Pinecone plus the Supabase
`rag_documents`/`rag_chunks` manifests:

```powershell
.\.venv\Scripts\python.exe scripts\load_official_sources.py --upload
```

The upload is idempotent and uses the namespace configured by
`PINECONE_NAMESPACE`. Unchanged chunks are not embedded again; use `--force`
only when you intentionally need to rebuild every vector. After upload, run
the live retrieval check explicitly:

```powershell
.\.venv\Scripts\python.exe scripts\check_rag.py --live
```

## Current limitations

- The public assignment flow is one prompt per `/api/execute` call; it does not
  yet preserve a case across follow-up prompts.
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
- The checked-in official PDFs are local snapshots whose freshness still needs
  release verification. Retrieved guidance is source-grounded information, not
  legal advice.
- Emergency guidance has a deterministic fallback, but the app does not contact
  emergency services, building management, tenants, or contractors.

See `TODO.md` for the prioritized path from this baseline to submission.
