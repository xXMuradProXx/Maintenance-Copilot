# Maintenance Copilot — RAG Agent for Tenant Maintenance Triage

Full-stack AI agent (course final project, *Introduction to Modern AI Agents*)
that turns messy tenant messages ("no heat again since yesterday") into
structured work orders: it classifies the issue against an HPD-style taxonomy,
retrieves landlord obligations from a housing-guidance corpus (RAG), offers
vendor appointment windows, books them, or escalates to the human manager —
with an explicit safety pre-filter, autonomy policy, and loop guard.

**Stack:** OpenAI (chat + embeddings) · Pinecone (vector DB) · FastAPI (Python)
· vanilla HTML/JS frontend · Vercel (serverless deployment).

## Project structure

```
maintenance-copilot/
├── api/
│   ├── index.py            # FastAPI entrypoint (Vercel serverless function)
│   └── _lib/               # underscore prefix = NOT deployed as functions
│       ├── agent.py        # supervisor loop, tools, autonomy policy, loop guard
│       ├── safety.py       # rule-based safety pre-filter (force-escalate/flag)
│       ├── taxonomy.py     # HPD-style problem taxonomy (structured source)
│       ├── vendors.py      # approved-vendor directory + calendar slots
│       ├── rag.py          # OpenAI embeddings + Pinecone retrieval
│       └── state.py        # Shared Case State (work order + decision trace)
├── data/housing_guidance/  # RAG corpus (10 markdown guidance docs)
├── public/index.html       # frontend (chat + live work-order + agent trace)
├── upload_data.py          # one-time ingestion: chunk → embed → Pinecone
├── requirements.txt
├── vercel.json             # rewrites /api/* to api/index.py, 60s max duration
└── .env.example
```

## 1. Run locally (PyCharm)

```bash
# in the project root
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then paste your real OPENAI_API_KEY + PINECONE_API_KEY

python upload_data.py       # one-time: builds the Pinecone index from data/

uvicorn api.index:app --reload
```

Open http://127.0.0.1:8000 — the frontend, API and interactive docs
(http://127.0.0.1:8000/docs) all run from one server.

## 2. Deploy to Vercel

1. Push the project to a GitHub repository (make sure `.env` is NOT committed —
   it's in `.gitignore`).
2. On https://vercel.com → **Add New… → Project** → import the repo. Framework
   preset: **Other**. No build command needed.
3. In **Settings → Environment Variables**, add `OPENAI_API_KEY` and
   `PINECONE_API_KEY` (and optionally `PINECONE_INDEX`, `OPENAI_MODEL`).
4. Deploy. Your agent is live at `https://<project>.vercel.app` for anyone with
   the link. `public/` is served statically; `/api/*` hits the Python function.

Note: `upload_data.py` runs **on your machine**, not on Vercel — the deployed
function only *queries* the Pinecone index you built locally.

## 3. Try these demo messages

| Message | Expected agent behavior |
|---|---|
| "The kitchen sink is clogged and water drains very slowly. Apt 4B." | ROUTINE plumbing → offers two plumber windows |
| "1" / "the first one works" | Books the chosen slot → status **Scheduled** |
| "No heat again since yesterday, apartment 12C" | Safety flag + RAG heat-season rules → EMERGENCY → **Escalated** |
| "I smell gas in my kitchen!!" | Force-escalate: bypasses the LLM loop, immediate 911/utility safety steps |
| "bathroom problem" | Missing facts → asks 1–2 questions → **Waiting for tenant info** |

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | required |
| `PINECONE_API_KEY` | — | required (RAG degrades gracefully without it) |
| `PINECONE_INDEX` | `maintenance-copilot` | index name |
| `OPENAI_MODEL` | `gpt-4o-mini` | supervisor model |
| `EMBED_MODEL` | `text-embedding-3-small` | 1536-dim embeddings |
