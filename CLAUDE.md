# Contract Research Assistant — Agent Handoff

> **Naming history**: this project was originally built as
> `knowledge-assistant-demo-v3` (third iteration of an agent-app reference
> build). User-facing identity has been renamed to
> `contract-research-assistant`. Internal infrastructure IDs created during
> the v3 era are preserved as historical names — see the Deployed app
> section + operational-gotchas below.

## Project

Reference build for an agent-app deployment. v3 ports v2's
`ResponsesAgent` (`mlflow.pyfunc.ResponsesAgent` subclass) to the
Apps-async pattern: module-level `@invoke()` / `@stream()` async
functions registered with `mlflow.genai.agent_server.AgentServer`.
Agent code runs inside the App process. **The port IS the deliverable,
not a side effect.**

## Stack (locked)

- Backend: Python FastAPI + Uvicorn + MLflow AgentServer
- Frontend: Vite + React + Tailwind (hand-rolled, no Databricks template)
- Auth: App SP for VS + LLM (OAuth scope constraints — see operational-gotchas)
- VS: `one-env-shared-endpoint-11` / `jreber_knowledge_assistant_demo.default.contracts_idx`
- LLM: `databricks-claude-sonnet-4-5`
- Workspace: `e2-demo-field-eng`
- Reference (read-only, do NOT fork): https://github.com/auschoi96/mas-demo-app

## File layout

```
knowledge-assistant-demo-v3/
├── app.yaml                  # Apps runtime config (OAuth scopes + env vars)
├── agent_config.yaml         # VS + LLM + retrieval config
├── databricks.yml            # DAB bundle (pipeline only — app via deploy.sh)
├── resources/setup_job.yml   # Multi-task pipeline job
├── pyproject.toml            # uv-native deps (Python 3.11+)
├── server/                   # FastAPI + AgentServer
│   ├── start_server.py       # entrypoint, mounts routes + static SPA
│   ├── agent.py              # @invoke / @stream port of v2's ResponsesAgent
│   ├── retrieval.py          # VS hybrid + reranker (uses App SP)
│   ├── auth.py               # OBO header resolution
│   ├── db.py                 # Lakebase psycopg pool (OAuthConnection)
│   ├── supervisor.py         # LLM-as-judge stub (KA_ENABLE_SUPERVISOR)
│   ├── config.py             # agent_config.yaml loader
│   └── routes/               # threads, feedback, documents
├── client/                   # Vite + React + Tailwind (hand-rolled)
├── notebooks/                # Data pipeline (lifted from v1)
│   ├── 00_ingest.py          # PDFs → raw_contracts
│   ├── 01_parse.py           # ai_parse_document → parsed_contracts
│   └── 02_chunk_index.py     # ai_prep_search → search_ready → VS index
├── data/                     # Source corpus (CC-BY 4.0 CUAD + synthetic)
├── src/synthetic_contract_generator.py   # regenerator
└── scripts/
    ├── start_local.sh        # uvicorn + vite dev servers
    ├── deploy.sh             # build + workspace upload + apps deploy
    ├── bootstrap_schema.sql  # Lakebase threads + messages tables
    └── download_cuad.py      # refresh CUAD corpus from HF
```

## Build phases (TaskList)

1. ✅ Read mas-demo-app references
2. ✅ Re-read the source `advanced_ka_model.py` + v1 `ContractAgent`
3. ✅ Invoke databricks-app-python skill
4. Scaffold repo (**current**)
5. Port ResponsesAgent → AgentServer @invoke/@stream
6. Build Vite + React + Tailwind chat client
7. Wire Lakebase chat history
8. Wire feedback (thumbs + free text)
9. Wire MLflow tracing → UC tables
10. Add in-app document viewer + supervisor scaffold
11. Deploy + smoke test

## Non-obvious things future-me will want to know

- **OBO-aware auth module**: `server/auth.py` resolves
  OBO → dev token → SP fallback. Used by `routes/documents.py` so PDF
  reads honor per-user Volume ACLs. Set `DISABLE_SP_FALLBACK=true` in prod
  to surface auth misconfigs loudly. The agent itself (VS + LLM) uses SP
  due to OAuth scope constraints (see operational-gotchas).
- **UC tracing day-one**: `app.yaml` sets `MLFLOW_TRACKING_URI=databricks`,
  `MLFLOW_TRACING_SQL_WAREHOUSE_ID`, and `KA_TRACE_*` env vars so OTel tables
  populate from the first request. v2 left this until Phase 4 and OTel tables
  stayed empty — don't repeat that.
- **End-user attribution**: `_tag_trace()` in `server/agent.py` writes
  `mlflow.trace.user` metadata from `X-Forwarded-Email` on every request. Phase
  4c from v2 — done day-one in v3.
- **VS index reuse**: v3 reuses v1's index (`contracts_idx`). Source data
  pipeline (`ai_parse_document` → `ai_prep_search` → Delta-Sync) lives in v1's
  repo — do not duplicate. If the index needs rebuilding, run v1's
  `notebooks/02_chunk_index.py`.
- **Streaming via `@stream()`**: AgentServer's `@stream()` decorator handles
  SSE wire format. Our handler `yield`s `ResponsesAgentStreamEvent` objects;
  the framework serializes to `data: ...\n\n` blocks. Frontend parses SSE
  per `client/src/lib/api.ts`.
- **`mlflow.genai.agent_server.get_request_headers()`** is the canonical way
  to read request headers from inside a `@invoke()` / `@stream()` handler.
  Don't try to thread `Request` through — AgentServer doesn't pass it.

## Operational gotchas (learned at deploy time)

- **Apps `user_authorization.scopes` don't grant legacy OAuth scopes.**
  - VS SDK rejects OBO with `Provided OAuth token does not have required scopes: all-apis`
  - FM API rejects OBO with `Provided OAuth token does not have required scopes: model-serving`
  - Workaround in v3: VS + LLM both use App SP, not OBO. End-user attribution is
    preserved via `mlflow.update_current_trace(metadata={'mlflow.trace.user': ...})`
    independent of the call principal. Don't try to declare `all-apis` or
    `model-serving` in `app.yaml` — they aren't valid Apps scopes.
- **CREATE OR REPLACE TABLE + drop-and-recreate VS index wipes table-level
  grants.** After re-running v1's `02_chunk_index.py`, the SP's `SELECT` on
  `contracts_idx` and `search_ready` had to be re-granted manually. If we
  re-index again, re-issue the four GRANTs in the deploy checklist below.

## Deployed app

- **App name:** `contract-research-assistant`
- **URL:** https://contract-research-assistant-1444828305810485.aws.databricksapps.com
- **SP client_id:** `c04024f5-eb69-4f22-8188-cc5ffa16c7ee`
- **Lakebase role:** `projects/ka-v3/branches/production/roles/cra-app`
  (`postgres_role` = SP client_id; project ID kept as historical `ka-v3`)
- **UC trace tables:** `jreber_knowledge_assistant_demo.audit.ka_v3_otel_*`
  (table prefix kept as historical `ka_v3`)
- **Logs:** open <URL>/logz
- **First deploy:** 2026-05-19 (as `ka-v3`) · Renamed: 2026-05-20

### Deploy-time grants already applied (don't repeat unless redoing)

```
# Postgres role + table perms (run as superuser):
databricks postgres create-role projects/ka-v3/branches/production \
  --role-id ka-v3-app \
  --json '{"spec":{"identity_type":"SERVICE_PRINCIPAL","postgres_role":"<SP>"}}'

# Then via psql:
GRANT USAGE ON SCHEMA public TO "<SP>";
GRANT SELECT, INSERT, UPDATE, DELETE ON threads, messages TO "<SP>";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "<SP>";

# UC + warehouse:
GRANT USE CATALOG ON CATALOG `jreber_knowledge_assistant_demo` TO `<SP>`;
GRANT USE SCHEMA  ON SCHEMA  `jreber_knowledge_assistant_demo`.`audit` TO `<SP>`;
GRANT MODIFY, SELECT ON TABLE `<cat>.<sch>.ka_v3_otel_spans|_logs|_annotations` TO `<SP>`;

databricks permissions update warehouses 4b9b953939869799 \
  --json '{"access_control_list":[{"service_principal_name":"<SP>","permission_level":"CAN_USE"}]}'
```

## Pre-deploy checklist (Task #11)

Local development uses my user's PAT and superuser Postgres role, which papers
over several auth issues that WILL bite on first deploy. Address before
declaring v3 working in production:

1. **Lakebase SP role + grants.** After `databricks apps create ka-v3` returns
   the SP client_id, run:
   ```
   databricks postgres create-role projects/ka-v3/branches/production \
     --role-id ka-v3-app \
     --json '{"spec":{"identity_type":"SERVICE_PRINCIPAL","postgres_role":"<sp-client-id>"}}'
   ```
   then via psql: `GRANT ALL ON threads, messages TO "<sp-client-id>";`. Update
   `PGUSER` in `app.yaml` to the SP client_id. Without this the App 503s every
   chat-history call.
2. **UC tracing perms.** SP needs `USE CATALOG jreber_knowledge_assistant_demo`,
   `USE SCHEMA audit`, `MODIFY` + `SELECT` on auto-created `ka_v3_otel_*` tables,
   `CAN USE` on warehouse `4b9b953939869799`. v2's OTel tables stayed empty
   because of these missing perms — do not skip.
3. **OBO + VectorSearch.** We pass the OBO JWT as `personal_access_token` to
   `VectorSearchClient` (server/retrieval.py). mas-demo-app does NOT do this —
   they use OBO only for serving endpoints. **Risk: VS may 401 with the OBO
   JWT.** Test immediately after deploy; if it fails, fall back to SP for VS
   only (instantiate VS via `service_principal_client_id`/`_secret` from the
   App's injected env vars).
4. **`DATABRICKS_HOST` scheme.** Apps inject bare hostname (no `https://`). Our
   `server/auth.py` strips trailing slashes but does NOT prepend `https://`.
   `WorkspaceClient` may normalize; if not, prepend explicitly.
5. **FM endpoint + warehouse access for SP.** Default Apps SPs usually have FM
   access; warehouse `CAN_USE` is not automatic — grant explicitly.
6. **SSE through the Apps proxy.** Local streaming is direct uvicorn → curl;
   production goes through Databricks' edge. Some proxy configs buffer SSE.
   Verify token-by-token delivery via Chrome DevTools after deploy.
7. **Static bundle path.** `start_server.py` includes
   `/app/python/source_code/client/out` as a candidate; `deploy.sh` already
   stages `client/out` into the upload. Confirm at deploy.

## Open questions / TODOs

- Lakebase instance: need to create one (or pick a shared FE instance) and put
  the `ENDPOINT_NAME` in `app.yaml`. Resource binding (PGHOST etc) happens via
  the App's Database resource UI.
- Trace warehouse: `app.yaml` defaults to `4b9b953939869799` (Shared UC
  Serverless — same as mas-demo-app). May need a different warehouse if SP
  doesn't have CAN_USE.
- Document viewer: still TBD — iframe a Volume PDF URL via signed URL? Or a
  pdf.js viewer? Defer until other pieces work.
- Supervisor scaffold: stub only — don't enable routing. Just shows the shape.

## Related memories

- `[[project-ka-demo]]` — full project history (v1, v2, v3)
- `[[apps-sp-vs-obo]]` — auth mode reasoning + the SP-vs-OBO tradeoffs
- `[[mlflow-feedback-from-express]]` — feedback POST pattern (porting from Express to FastAPI)
- `[[reference_lakebase_apps_autoscaling]]` — Lakebase setup quirks
- `[[mlflow-trace-storage-paths]]` — two-store model behind UC tracing
- `[[feedback_ai_dev_kit_reading]]` — re-read AI Dev Kit skill files before building each component
