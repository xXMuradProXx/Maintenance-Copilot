# Supabase setup

The application uses Supabase only from the Python backend. Never copy
`SUPABASE_SECRET_KEY` into `public/index.html` or commit `.env`.

## Apply migration 001

1. Open the Supabase project dashboard.
2. Select **SQL Editor**.
3. Create a new query.
4. Open `supabase/migrations/001_initial_schema.sql` locally and copy its full
   contents into the query.
5. Click **Run** once.

The migration runs inside a transaction. If any statement fails, Supabase
rolls the migration back instead of leaving a partially-created schema. The
file is also written to be safe to run again after correcting an error.

The migration creates:

- `hpd_taxonomy` and the `search_hpd_taxonomy` database function;
- durable `cases`, `messages`, and ordered `case_events`;
- `rag_documents` and `rag_chunks` as the Pinecone ingestion manifest;
- future-facing `vendors`, `vendor_slots`, and `appointments` tables;
- updated-at triggers, constraints, indexes, and backend-only security.

Row Level Security is enabled on every application table and no public access
policies are created. The backend secret key uses Supabase's `service_role`;
the anonymous browser cannot read or write these tables directly.

## Verify the migration

From the project root with the virtual environment installed:

```powershell
.\.venv\Scripts\python.exe scripts\check_supabase.py
```

Every table should print `[ok]`. The taxonomy table will remain empty until the
next step loads `data/Housing_Maintenance_Code_Complaints_and_Problems_grouped.csv`.

## Load the HPD taxonomy

The app uses the small grouped CSV, not the raw 9 GB complaint export. First
validate its exact schema, 641 rows, source types, and complaint totals without
writing anything:

```powershell
.\.venv\Scripts\python.exe scripts\load_taxonomy.py --dry-run
```

Then load it. This is an idempotent upsert, so rerunning it updates the same
source rows instead of creating duplicates:

```powershell
.\.venv\Scripts\python.exe scripts\load_taxonomy.py
```

Finally, exercise the same agent-facing search path used by `classify_issue`:

```powershell
.\.venv\Scripts\python.exe scripts\check_taxonomy_search.py
```

The search result's `urgency` is the direct mapping of the imported HPD
complaint type. No handwritten guidance or internal playbook overrides it.

## Index official PDFs

The default command is a local-only extraction/chunking dry run:

```powershell
.\.venv\Scripts\python.exe scripts\load_official_sources.py --dry-run
```

Only the explicit `--upload` mode contacts LLMod, Pinecone, and Supabase. It
upserts the three official document manifests and their page-bounded chunks:

```powershell
.\.venv\Scripts\python.exe scripts\load_official_sources.py --upload
```
