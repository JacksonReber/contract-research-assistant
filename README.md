# Contract Research Assistant

End-to-end reference build for an **agent app on Databricks** — a RAG agent
over a contract corpus, deployed as a Databricks App with:

- **Agent**: Python + FastAPI + MLflow `AgentServer` (`@invoke` / `@stream`
  async handlers — the Apps-async pattern, not Model Serving)
- **Frontend**: Vite + React + Tailwind, served as a static bundle
- **Retrieval**: Vector Search Hybrid + `DatabricksReranker`
- **LLM**: `databricks-claude-sonnet-4-5` (Foundation Model API)
- **Chat history**: Lakebase Autoscaling (Postgres) with per-user threads
- **Feedback**: thumbs + free-text comment → MLflow Assessments API
- **Tracing**: MLflow → Unity Catalog OTel tables (queryable + dashboardable)
- **In-app PDF viewer**: opens source document at the cited page
- **End-user attribution**: `mlflow.trace.user` metadata on every trace

Reference build for migrating an existing `ResponsesAgent` to the
Apps-async pattern.

## Repo layout

```
.
├── server/                FastAPI + AgentServer (agent runs inside the App)
│   ├── start_server.py    App entrypoint, mounts routes + static SPA
│   ├── agent.py           @invoke / @stream — the port of v2's ResponsesAgent
│   ├── retrieval.py       VS hybrid + reranker (App SP, see CLAUDE.md gotchas)
│   ├── auth.py            OBO header resolution
│   ├── db.py              Lakebase Postgres pool (OAuthConnection)
│   ├── supervisor.py      LLM-as-judge scaffold (stub, KA_ENABLE_SUPERVISOR=true)
│   └── routes/            threads (chat history), feedback, documents (PDF)
├── client/                Vite + React + Tailwind (hand-rolled)
│   └── src/{components,lib,pages,styles}
├── notebooks/             Data pipeline (run once)
│   ├── 00_ingest.py       PDFs → raw_contracts (UC Volume + manifest)
│   ├── 01_parse.py        ai_parse_document → parsed_contracts (multi-modal)
│   └── 02_chunk_index.py  ai_prep_search → search_ready → VS Delta-Sync index
├── data/                  Source corpus
│   ├── cuad/              50 CUAD v1 contracts (CC-BY 4.0, see data/NOTICE.md)
│   ├── synthetic/         16 synthetic MSSA/SOW/CO PDFs (hierarchical refs)
│   └── NOTICE.md          License + attribution
├── src/
│   └── synthetic_contract_generator.py   Regenerate the synthetic PDFs
├── databricks.yml         DAB bundle (pipeline only — app deploys via deploy.sh)
├── resources/
│   └── setup_job.yml      Multi-task pipeline job
├── scripts/
│   ├── start_local.sh     uvicorn :8000 + vite :3000 dev loop
│   ├── deploy.sh          build → stage → workspace upload → apps deploy
│   ├── bootstrap_schema.sql  Lakebase threads + messages tables
│   └── download_cuad.py   Optional — refresh CUAD corpus from HuggingFace
├── agent_config.yaml      VS endpoint/index + LLM + retrieval tuning
├── app.yaml               Apps runtime config (OAuth scopes, env vars)
├── pyproject.toml         uv-native (Python 3.11+)
└── CLAUDE.md              Operational handoff notes for future AI sessions
```

## End-to-end setup

The full lifecycle is two phases: **data pipeline once**, then **app deploy
+ iterate**.

### Phase 1 — Data pipeline (run once per workspace)

Provisions the catalog/schemas/volume, parses every PDF in `data/` via
`ai_parse_document`, chunks via `ai_prep_search`, and creates the Vector
Search Delta-Sync index.

```bash
# 1. Validate the bundle
databricks bundle validate -p e2-demo-field-eng

# 2. Deploy the bundle (uploads notebooks + sets up the job)
databricks bundle deploy -p e2-demo-field-eng

# 3. Run the pipeline (~5-10 min)
databricks bundle run setup_job -p e2-demo-field-eng
```

After this completes you will have:

- `jreber_knowledge_assistant_demo` catalog
- `default` schema with `raw_contracts`, `parsed_contracts`, `search_ready`
  Delta tables
- `audit` schema for trace + audit tables
- `contracts` UC Volume with the source PDFs
- `jreber_knowledge_assistant_demo.default.contracts_idx` VS Delta-Sync index

> Variables (catalog, vs_endpoint, etc.) live in `databricks.yml`. Override
> per-deploy with `--var key=value`.

### Phase 2 — Provision the App's runtime dependencies

The app itself depends on a Lakebase project (for chat history) and an MLflow
experiment (for tracing). These are one-time setup steps.

```bash
# Create the Lakebase Autoscaling project (any project_id works; we use `cra`)
databricks postgres create-project cra -p e2-demo-field-eng \
  --json '{"spec":{"display_name":"Contract Research Assistant","pg_version":"17"}}'

# Bootstrap the chat-history schema (run psql with the OAuth token as password)
PG_TOKEN=$(databricks postgres generate-database-credential -p e2-demo-field-eng \
  --json '{"endpoint":"projects/cra/branches/production/endpoints/primary"}' \
  --output json | jq -r .token)
PGPASSWORD="$PG_TOKEN" psql \
  -h "$(databricks postgres get-endpoint projects/cra/branches/production/endpoints/primary \
        -p e2-demo-field-eng --output json | jq -r .status.hosts.host)" \
  -U your-email@databricks.com -d databricks_postgres \
  -f scripts/bootstrap_schema.sql
```

> **Historical note:** The currently-deployed instance uses `projects/ka-v3` —
> the Lakebase project keeps its original development-name internally. New
> deploys can use any project name; the app reads `ENDPOINT_NAME` /
> `PGHOST` from `app.yaml`.

### Phase 3 — Deploy the App

```bash
# Create the App (gets a service-principal client_id from Databricks)
databricks apps create contract-research-assistant -p e2-demo-field-eng

# Grab the SP client_id from the create response (or `databricks apps get`).
# Register the SP as a Lakebase Postgres role + grant table perms:
databricks postgres create-role projects/<project>/branches/production \
  -p e2-demo-field-eng --role-id cra-app \
  --json '{"spec":{"identity_type":"SERVICE_PRINCIPAL","postgres_role":"<SP_CLIENT_ID>"}}'

# Via psql (same connection string as above):
GRANT USAGE ON SCHEMA public TO "<SP_CLIENT_ID>";
GRANT SELECT, INSERT, UPDATE, DELETE ON threads, messages TO "<SP_CLIENT_ID>";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "<SP_CLIENT_ID>";

# UC + warehouse grants (run as SQL):
GRANT USE CATALOG ON CATALOG jreber_knowledge_assistant_demo TO `<SP_CLIENT_ID>`;
GRANT USE SCHEMA  ON SCHEMA  jreber_knowledge_assistant_demo.default TO `<SP_CLIENT_ID>`;
GRANT USE SCHEMA  ON SCHEMA  jreber_knowledge_assistant_demo.audit   TO `<SP_CLIENT_ID>`;
GRANT SELECT      ON TABLE   jreber_knowledge_assistant_demo.default.contracts_idx TO `<SP_CLIENT_ID>`;
GRANT SELECT      ON TABLE   jreber_knowledge_assistant_demo.default.search_ready  TO `<SP_CLIENT_ID>`;
GRANT READ VOLUME ON VOLUME  jreber_knowledge_assistant_demo.default.contracts     TO `<SP_CLIENT_ID>`;
-- Then for each OTel table that exists after the first trace, MODIFY + SELECT:
GRANT MODIFY, SELECT ON TABLE jreber_knowledge_assistant_demo.audit.ka_v3_otel_spans       TO `<SP_CLIENT_ID>`;
GRANT MODIFY, SELECT ON TABLE jreber_knowledge_assistant_demo.audit.ka_v3_otel_logs        TO `<SP_CLIENT_ID>`;
GRANT MODIFY, SELECT ON TABLE jreber_knowledge_assistant_demo.audit.ka_v3_otel_annotations TO `<SP_CLIENT_ID>`;

# Warehouse CAN_USE (Apps SDK can also do this via permissions update):
databricks permissions update warehouses 4b9b953939869799 -p e2-demo-field-eng \
  --json '{"access_control_list":[{"service_principal_name":"<SP_CLIENT_ID>","permission_level":"CAN_USE"}]}'

# Set PGUSER in app.yaml to <SP_CLIENT_ID>, then deploy:
./scripts/deploy.sh contract-research-assistant --profile e2-demo-field-eng
```

The deploy script will build the frontend, stage the source code, upload to
the workspace, and trigger the App deployment. Logs at `<app-url>/logz`.

## Local development

```bash
cp .env.example .env.local             # fill DATABRICKS_HOST + DATABRICKS_TOKEN
uv sync                                 # install Python deps
cd client && npm install && cd ..       # install client deps
./scripts/start_local.sh                # uvicorn :8000 + vite :3000
open http://localhost:3000
```

Local dev uses your PAT for outbound calls (no Apps proxy), so the OBO chain
is bypassed and per-user ACL behavior won't show up until you deploy.

## Auth model (important — read `CLAUDE.md` for the full story)

Both the Vector Search SDK and the Foundation Model API require legacy OAuth
scopes (`all-apis` / `model-serving`) that are NOT declarable in Apps'
`user_authorization` block. This app therefore uses the **App SP** for all
downstream API calls (VS + LLM + Lakebase + UC writes). End-user attribution
is preserved by setting `mlflow.trace.user` metadata explicitly from
`X-Forwarded-Email` on each request — the trace is attributed correctly
even though the API calls themselves run as the SP.

## See also

- `CLAUDE.md` — full operational notes, gotchas, and pre-deploy checklist
- `agent_config.yaml` — retrieval + LLM tuning knobs
- `app.yaml` — Apps runtime config (OAuth scopes, env vars)
- `data/NOTICE.md` — corpus licensing
