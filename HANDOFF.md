## Overview
- What you get: a self-contained Databricks Apps reference build that ports a `ResponsesAgent` to the Apps-async pattern (`@invoke` / `@stream` async decorators inside the App, no Model Serving endpoint), with VS retrieval, Lakebase chat history, MLflow Assessments feedback, and UC trace storage
- Bundle has two halves:
    - **Data pipeline** (`databricks.yml` + `notebooks/`): PDFs → `parsed_contracts` → `search_ready` → VS Delta-Sync index
    - **App** (`server/` + `client/` + `app.yaml`): FastAPI + AgentServer + Vite/React, deployed via `scripts/deploy.sh`
- Your work: drop in your corpus, change ~6 config values, run the bundle, create the App, grant the SP. ~30–45 minutes if your VS endpoint + SQL warehouse already exist.

## Prerequisites
- **Vector Search endpoint** (standard or storage-optimized)
    - Set in: `databricks.yml` → `variables.vs_endpoint.default` (flows into the pipeline notebooks via `${var.vs_endpoint}`)
    - Set in: `agent_config.yaml` → `agent.vector_index.endpoint` (read by the app at query time)
- **SQL warehouse** the App SP can `CAN USE`. Powers UC trace writes + `mlflow.log_feedback` reads.
    - Set in: `app.yaml` → `MLFLOW_TRACING_SQL_WAREHOUSE_ID`
- **Foundation Model API access** for the chat model you pick (default `databricks-claude-sonnet-4-5`)
    - Set in: `agent_config.yaml` → `agent.llm.endpoint`
- **Unity Catalog** with a catalog + schema you control. You'll create `raw_contracts`, `parsed_contracts`, `search_ready`, the VS index, and the auto-created OTel trace tables.
    - Set in: `databricks.yml` → `variables.catalog.default` / `variables.schema.default` / `variables.audit_schema.default` / `variables.volume.default`
    - Set in: `app.yaml` → `KA_TRACE_CATALOG` / `KA_TRACE_SCHEMA` / `KA_TRACE_TABLE_PREFIX` (controls where MLflow writes the OTel tables)
    - Set in: `agent_config.yaml` → `agent.vector_index.name` (the full `<catalog>.<schema>.<index>` path)
- **DBR 17.1+** available in your workspace (required for `ai_parse_document`)
    - Set in: `resources/setup_job.yml` → each task's `new_cluster.spark_version` (only change if 17.1 isn't available; bump to 17.2.x or whatever 17.1+ runtime is published in your workspace)
- **Lakebase Autoscaling** if you want chat history. Skippable — agent + UI still work without it.
    - Set in: `app.yaml` → `ENDPOINT_NAME` / `PGHOST` / `PGUSER` / `PGDATABASE` (leave blank to disable; `server/db.py` no-ops gracefully)

## Customize: Source Corpus
- **Input:** drop your PDFs into `data/<your-folder>/` before running the pipeline
- **Output:** `00_ingest.py` copies them into a UC Volume, then `01_parse.py` runs `ai_parse_document`
- If your PDFs already live in a UC Volume, skip `data/` entirely and point `00_ingest.py` at your existing Volume path (or just write your own Delta of `(doc_id, source_type, content)` and skip 00 too)

```yaml
# resources/setup_job.yml — tweak base_parameters per task if your paths differ
- task_key: ingest
  notebook_task:
    notebook_path: ../notebooks/00_ingest.py
    base_parameters:
      catalog: ${var.catalog}
      schema:  ${var.schema}
      volume:  ${var.volume}
```

## Customize: `databricks.yml` Variables
- Six variables drive every notebook + the resulting catalog/schema/volume/index naming
- Override per-target with `--var key=value` or change defaults inline

```yaml
variables:
  catalog:      { default: <your-catalog> }              # ← required
  schema:       { default: default }
  audit_schema: { default: audit }                       # for trace tables
  volume:       { default: contracts }                   # UC Volume name
  vs_endpoint:  { default: <your-vector-search-endpoint> }   # ← required

targets:
  dev:
    workspace: { profile: <your-cli-profile> }           # ← required
```

## Customize: `agent_config.yaml`
- This is where retrieval tuning + LLM choice + system prompt live
- The `columns:` list must match the columns your `search_ready` table actually exposes (the default matches what `notebooks/02_chunk_index.py` writes)

```yaml
agent:
  name: <your-agent-name>
  description: '<one-liner shown in the App's top bar>'

  vector_index:
    name:     <catalog>.<schema>.contracts_idx
    endpoint: <your-vector-search-endpoint>
    columns:
      - chunk_id
      - doc_id
      - source_type
      - source_path
      - page_num
      - chunk_to_retrieve
      - image_uri

  retrieval:
    num_results: 20          # bump higher for cross-doc compare; 5-10 is plenty for single-doc QA
    query_type: HYBRID       # vector + BM25

  llm:
    endpoint: databricks-claude-sonnet-4-5
    temperature: 0.0
    max_tokens: 2048
    system_prompt: |
      <REWRITE THIS for your corpus.>
      Today's default is contract-research tone. If you're indexing earnings
      calls, support tickets, or policy docs, change the persona + citation
      format here. The agent.py code does NOT parse the prompt — it forwards
      it verbatim to the LLM with the retrieved chunks appended.
```

> [!TIP]
> Citations come from the VS chunks themselves (`custom_outputs.citations`), NOT from the LLM's prose. You don't need to instruct the LLM to "list sources at the bottom" — the UI renders citations from structured data. If you want clean answer prose, drop the "Sources: ..." line from the default system prompt.

## Customize: `app.yaml`
- Three env-var groups to update: MLflow tracing, Lakebase connection, allowed Volume prefix for the PDF viewer

```yaml
env:
  # --- MLflow tracing → UC --------------------------------------------------
  - { name: MLFLOW_TRACKING_URI,            value: databricks }
  - { name: MLFLOW_EXPERIMENT_NAME,         value: /Shared/<your-experiment-name> }
  - { name: MLFLOW_TRACING_SQL_WAREHOUSE_ID, value: '<your-warehouse-id>' }
  - { name: KA_TRACE_CATALOG,               value: <your-catalog> }
  - { name: KA_TRACE_SCHEMA,                value: <your-audit-schema> }
  - { name: KA_TRACE_TABLE_PREFIX,          value: <your-prefix> }   # generates <prefix>_otel_*

  # --- Lakebase chat history (skip if not using Lakebase) -------------------
  - { name: ENDPOINT_NAME, value: 'projects/<your-project>/branches/production/endpoints/primary' }
  - { name: PGHOST,        value: '<your-lakebase-host>.database.<region>.cloud.databricks.com' }
  - { name: PGDATABASE,    value: 'databricks_postgres' }
  - { name: PGPORT,        value: '5432' }
  - { name: PGSSLMODE,     value: 'require' }
  - { name: PGUSER,        value: '<APP_SP_CLIENT_ID>' }      # ← fill in AFTER `databricks apps create`

  # --- PDF viewer Volume allowlist (optional) -------------------------------
  - { name: KA_ALLOWED_VOLUME_PREFIXES, value: '/Volumes/<your-catalog>/<your-schema>/<your-volume>/' }
```

- **OAuth scopes block:** leave as shipped. We declare `serving.serving-endpoints` and `vectorsearch.vector-search-endpoints`, but the app actually uses the App SP for both VS + LLM calls (see [Auth Pattern](#auth-pattern-read-this-before-flipping-anything-to-obo)). The scope declarations don't hurt — keep them in case you want to wire OBO into a specific code path later.

## Provision Lakebase (skip if no chat history)
- Create the project, register the SP after the App exists, GRANT tables
- The schema lives in `scripts/bootstrap_schema.sql` (`threads` + `messages` + indexes)

```bash
databricks postgres create-project <your-project-id> \
  --json '{"spec":{"display_name":"<Your App Name>","pg_version":"17"}}'

# After `databricks apps create` (next section):
databricks postgres create-role projects/<your-project-id>/branches/production \
  --role-id app-sp \
  --json '{"spec":{"identity_type":"SERVICE_PRINCIPAL","postgres_role":"<APP_SP_CLIENT_ID>"}}'

# Bootstrap the schema (run psql with your user identity):
psql -h <PGHOST> -U <your-email> -d databricks_postgres -f scripts/bootstrap_schema.sql

# Then grant the App SP table perms (still as your user):
psql -h <PGHOST> -U <your-email> -d databricks_postgres -c '
  GRANT USAGE ON SCHEMA public TO "<APP_SP_CLIENT_ID>";
  GRANT SELECT, INSERT, UPDATE, DELETE ON threads, messages TO "<APP_SP_CLIENT_ID>";
  GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "<APP_SP_CLIENT_ID>";
'
```

> [!NOTE]
> Auth tokens for Lakebase rotate on the 1-hour OAuth cycle. The `OAuthConnection` class in `server/db.py` regenerates the token on every new pooled connection; `max_lifetime=2700` (45 min) recycles connections before token expiry. **Don't lower max_lifetime past 2700** or you'll occasionally hand out connections with expired credentials.

## Grants: App SP on your UC + Warehouse
- After `databricks apps create <name>` returns the App's `service_principal_client_id`, run these in your workspace (SQL editor or via the SDK)
- All four OTel tables must be granted, even ones you don't think you use — see the WARNING below

```sql
GRANT USE CATALOG ON CATALOG <your-catalog>                            TO `<APP_SP_CLIENT_ID>`;
GRANT USE SCHEMA  ON SCHEMA  <your-catalog>.<your-schema>              TO `<APP_SP_CLIENT_ID>`;
GRANT USE SCHEMA  ON SCHEMA  <your-catalog>.<your-audit-schema>        TO `<APP_SP_CLIENT_ID>`;
GRANT SELECT      ON TABLE   <your-catalog>.<your-schema>.contracts_idx     TO `<APP_SP_CLIENT_ID>`;
GRANT SELECT      ON TABLE   <your-catalog>.<your-schema>.search_ready      TO `<APP_SP_CLIENT_ID>`;
GRANT READ VOLUME ON VOLUME  <your-catalog>.<your-schema>.<your-volume>     TO `<APP_SP_CLIENT_ID>`;

-- All four OTel tables (they're auto-created on the first trace; you can
-- pre-create empty Delta tables OR grant after the first request).
GRANT MODIFY, SELECT ON TABLE <your-catalog>.<your-audit-schema>.<prefix>_otel_spans       TO `<APP_SP_CLIENT_ID>`;
GRANT MODIFY, SELECT ON TABLE <your-catalog>.<your-audit-schema>.<prefix>_otel_logs        TO `<APP_SP_CLIENT_ID>`;
GRANT MODIFY, SELECT ON TABLE <your-catalog>.<your-audit-schema>.<prefix>_otel_annotations TO `<APP_SP_CLIENT_ID>`;
GRANT MODIFY, SELECT ON TABLE <your-catalog>.<your-audit-schema>.<prefix>_otel_metrics     TO `<APP_SP_CLIENT_ID>`;
```

```bash
# Warehouse CAN_USE via permissions API
databricks permissions update warehouses <your-warehouse-id> \
  --json '{"access_control_list":[{"service_principal_name":"<APP_SP_CLIENT_ID>","permission_level":"CAN_USE"}]}'
```

> [!WARNING]
> Miss any of the four OTel tables (especially `_otel_metrics`, easy to forget) and `mlflow.set_experiment(trace_location=UnityCatalog(...))` silently fails to attach the trace_location tags. Traces still write somewhere, but to the default MLflow store, NOT to UC. You'll see `Could not set UC-backed MLflow experiment ... PERMISSION_DENIED` in the app logs.

## Auth Pattern (read this before flipping anything to OBO)
- VS SDK and Foundation Model API both check for **legacy OAuth scopes** (`all-apis` and `model-serving` respectively) that are NOT declarable in Apps `user_authorization.scopes`
- OBO tokens scoped to `serving.serving-endpoints` / `vectorsearch.vector-search-endpoints` are **rejected** by both APIs
- The bundle ships with `server/retrieval.py` and `server/agent.py` configured to use the App SP for VS + LLM. End-user identity is preserved via `mlflow.update_current_trace(metadata={'mlflow.trace.user': email})` in `_tag_trace` — the trace shows the actual user even though the API call is made by the SP.
- If you need per-user enforcement of VS index ACLs or LLM endpoint ACLs, the workaround is to call those APIs from a separate process that has a real PAT-style OAuth grant, NOT from inside the Apps proxy

## Customize the Pipeline (if your data shape differs)
- `notebooks/02_chunk_index.py` projects specific fields out of `ai_prep_search`'s VARIANT output. If your downstream code expects different column names, change the projection here.

```sql
-- The critical projection in 02_chunk_index.py — adjust column names if needed
SELECT
  concat(doc_id, '__', cast(variant_get(chunk, '$.chunk_position','INT') AS STRING)) AS chunk_id,
  doc_id, source_type, source_path,
  cast(variant_get(chunk, '$.chunk_to_retrieve','STRING')  AS STRING) AS chunk_to_retrieve,
  cast(variant_get(chunk, '$.chunk_to_embed',   'STRING')  AS STRING) AS chunk_to_embed,
  cast(variant_get(chunk, '$.pages[0].page_id', 'INT')     AS INT)    AS page_num,
  cast(variant_get(chunk, '$.pages[0].image_uri','STRING') AS STRING) AS image_uri
FROM (
  SELECT explode(variant_get(ai_prep_search(parsed), '$.document.contents', 'ARRAY<VARIANT>')) AS chunk
  FROM parsed_contracts
);
```

> [!WARNING]
> Use `$.pages[0].page_id`, NOT `$.pages[0].page_number`. The latter silently returns NULL and breaks every `#page=N` deep-link in the PDF viewer. We learned this the hard way.

## Optional: Bump the LLM
- Change `agent_config.yaml.llm.endpoint` to any FM endpoint your SP has `CAN_QUERY` on
- We use Sonnet 4.5; Opus is stronger reasoning, Haiku is cheaper/faster, Gemini 2.5 Pro gives you 1M context if you need to skip retrieval and stuff the whole doc in

```yaml
llm:
  endpoint: databricks-claude-opus-4-6        # higher quality, ~3x cost
  # endpoint: databricks-claude-haiku-4-5     # cheaper, lower quality
  # endpoint: databricks-gemini-2-5-pro       # 1M context
```

## Optional: Skip Lakebase Entirely
- Leave `ENDPOINT_NAME`, `PGHOST`, `PGUSER` blank in `app.yaml`
- `server/db.py` detects unconfigured state, sets `pool = None`, and the routes 503 gracefully
- The frontend (ThreadList) hides the conversations sidebar when the chat-history API returns 503
- Net effect: agent + citations + feedback + PDF viewer all still work; just no per-user thread persistence

## Optional: Turn On the Supervisor Judge
- `server/supervisor.py` is a fully-written LLM-as-judge groundedness scorer (calls a second LLM after every response to score 0-1, writes the score as an MLflow Assessment with `source_type=LLM_JUDGE`)
- Shipped **off by default**. Flip the env var to enable:

```yaml
env:
  - { name: KA_ENABLE_SUPERVISOR, value: 'true' }
```

- Trade-offs: ~2x LLM cost per request, +1-3s latency on the chat call. Best practice is to calibrate the judge prompt against a labeled eval set before relying on its scores.

## What to Skip (don't waste time on these)
- **Don't change the SSE event schema.** AgentServer expects `ResponsesAgentStreamEvent` shapes. The frontend parses by `type:`. Adding custom event types is fine; renaming the standard ones breaks the UI.
- **Don't add the OAuth scopes you think you need** (`all-apis`, `model-serving`). They aren't valid Apps user_authorization scope strings.
- **Don't flip `server/retrieval.py` back to OBO** without reading the [Auth Pattern](#auth-pattern-read-this-before-flipping-anything-to-obo) section above — the Vector Search backend has reliability caveats with OBO scopes in some workspaces.
- **Don't add a `requirements.txt`.** The Apps runtime supports `pyproject.toml` + `uv.lock` natively. Stick to uv.
