## Overview
- RAG agent over a multi-modal contract corpus (50 CUAD v1 + 16 synthetic MSSAs/SOWs/COs)
- Deployed as a Databricks App. Agent code runs **inside the App process** via MLflow's `AgentServer` (`@invoke` + `@stream` async decorators). No separate Model Serving endpoint.
- Hybrid Vector Search + `DatabricksReranker` + Claude Sonnet 4.5. Every answer carries structured citations from VS chunks (not parsed from LLM prose).
- Lakebase Postgres for per-user chat threads. MLflow Assessments for thumbs + free-text feedback. Unity Catalog OTel tables for all traces.
- Reference build for any agent-on-Apps deployment.

## High Level Flow

### Data Prep: Ingestion + Parsing
- **Input:** PDFs in `data/cuad/` + `data/synthetic/` (66 contracts, ~9 MB)
- **Output:** `parsed_contracts` Delta table with a multi-modal VARIANT column
- Sequence:
    - `notebooks/00_ingest.py` copies PDFs into a UC Volume, writes `raw_contracts` Delta with a sha256 idempotency key
    - `notebooks/01_parse.py` runs `ai_parse_document` on each row, projects to `parsed_contracts`
- Multi-modal: passing `imageOutputPath` extracts page images to a Volume; chunks later reference them as `image_uri`
- DBR 17.1+ required for `ai_parse_document`

```python
# notebooks/01_parse.py (essence)
df = spark.read.format("binaryFile").load(volume_path)
parsed = df.withColumn(
    "parsed",
    expr("ai_parse_document(content, map('imageOutputPath', :img_path))")
)
parsed.write.mode("overwrite").saveAsTable(parsed_table)
```

- **Docs:** [`ai_parse_document`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document) · [Unity Catalog Volumes](https://docs.databricks.com/aws/en/volumes/)

### Data Prep: Chunking
- **Input:** `parsed_contracts` (one row per PDF, VARIANT payload)
- **Output:** `search_ready` (one row per chunk, ready for VS Delta-Sync)
- `ai_prep_search` emits a structured chunk array. Critical fields: `chunk_to_embed` (embedding text), `chunk_to_retrieve` (display text), `chunk_position`, `pages[0].page_id`, `pages[0].image_uri`

> [!WARNING]
> Use `$.pages[0].page_id` for page numbers, NOT `$.pages[0].page_number`. The latter silently returns NULL and breaks every downstream `#page=N` deep-link in the document viewer.

```sql
CREATE OR REPLACE TABLE search_ready AS
WITH chunks AS (
  SELECT doc_id, source_type, path AS source_path,
         explode(variant_get(ai_prep_search(parsed), '$.document.contents', 'ARRAY<VARIANT>')) AS chunk
  FROM parsed_contracts
  WHERE try_cast(parsed:error_status AS STRING) IS NULL
)
SELECT
  concat(doc_id, '__', cast(variant_get(chunk, '$.chunk_position','INT')    AS STRING))  AS chunk_id,
  doc_id, source_type, source_path,
  cast(variant_get(chunk, '$.chunk_to_retrieve','STRING')   AS STRING) AS chunk_to_retrieve,
  cast(variant_get(chunk, '$.chunk_to_embed','STRING')      AS STRING) AS chunk_to_embed,
  cast(variant_get(chunk, '$.pages[0].page_id','INT')       AS INT)    AS page_num,
  cast(variant_get(chunk, '$.pages[0].image_uri','STRING')  AS STRING) AS image_uri
FROM chunks
WHERE variant_get(chunk, '$.chunk_to_retrieve', 'STRING') IS NOT NULL;

ALTER TABLE search_ready SET TBLPROPERTIES (delta.enableChangeDataFeed = true);
```

- **Docs:** [`ai_prep_search`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_prep_search) · [Delta CDF](https://docs.databricks.com/aws/en/delta/delta-change-data-feed)

### Data Prep: Vector Search Index
- **Input:** `search_ready` with `chunk_to_embed` text + CDF enabled
- **Output:** Delta-Sync VS index `contracts_idx` on `one-env-shared-endpoint-11`
- Managed embeddings via `databricks-gte-large-en` (1024 dim). No manual embedding step.
- Pipeline type `TRIGGERED` (sync on demand) vs `CONTINUOUS` (auto-sync on every Delta change). Picked `TRIGGERED` for cost.

```python
from databricks.vector_search.client import VectorSearchClient
vsc = VectorSearchClient(disable_notice=True)
vsc.create_delta_sync_index(
    endpoint_name="one-env-shared-endpoint-11",
    source_table_name="jreber_knowledge_assistant_demo.default.search_ready",
    index_name="jreber_knowledge_assistant_demo.default.contracts_idx",
    pipeline_type="TRIGGERED",
    primary_key="chunk_id",
    embedding_source_column="chunk_to_embed",
    embedding_model_endpoint_name="databricks-gte-large-en",
)
```

- **Docs:** [Create + query Vector Search](https://docs.databricks.com/aws/en/generative-ai/create-query-vector-search) · [Vector Search overview](https://docs.databricks.com/aws/en/generative-ai/vector-search)

### Agent: ResponsesAgent → AgentServer Port
- **Pattern shift:** old shape subclassed `mlflow.pyfunc.ResponsesAgent` and deployed to Model Serving. New shape is **module-level async functions decorated with `@invoke()` / `@stream()`** registered with `mlflow.genai.agent_server.AgentServer`. Agent code runs inside the App's FastAPI process. No serving endpoint.
- AgentServer auto-wires `POST /invocations` (handles both streaming and non-streaming based on body `stream: true`), `GET /info`, `GET /health`. We add `/api/config`, `/api/whoami`, `/api/threads/*`, `/api/feedback`, `/api/documents` on top.
- The `@stream` handler yields `ResponsesAgentStreamEvent` objects. AgentServer serializes them to `data: {...}\n\n` SSE blocks. Frontend parses via `client/src/lib/api.ts`.

```python
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest, ResponsesAgentResponse, ResponsesAgentStreamEvent,
)

@stream()
async def _stream(request: ResponsesAgentRequest):
    chunks = await retrieve(...)
    citations = _build_citations(chunks)
    async for delta in _stream_tokens(query, chunks):
        yield ResponsesAgentStreamEvent(
            type="response.output_text.delta", item_id=msg_id, delta=delta
        )
    yield ResponsesAgentStreamEvent(
        type="response.output_item.done",
        item={"id": msg_id, "type": "message", "role": "assistant",
              "content": [{"type": "output_text", "text": full_text}]},
        custom_outputs={"citations": citations, "trace_id": _current_trace_id()},
    )
```

- **Docs:** [Migrate agent to Databricks Apps](https://docs.databricks.com/aws/en/generative-ai/agent-framework/migrate-agent-to-apps) · [Author an AI agent](https://docs.databricks.com/aws/en/generative-ai/agent-framework/author-agent)

### Agent: Retrieval with Reranker
- VS query uses Hybrid (vector + BM25 keyword) with `DatabricksReranker` against the `chunk_to_retrieve` column
- 20 chunks pulled per query. Bumped from the typical 3-5 to handle cross-doc compare scenarios.
- VS SDK is synchronous, so `asyncio.to_thread` wraps the call to avoid blocking the event loop

```python
from databricks.vector_search.reranker import DatabricksReranker

def _search_sync(query: str):
    idx = vs_client.get_index(endpoint_name=..., index_name=...)
    return idx.similarity_search(
        query_text=query,
        columns=["chunk_id", "doc_id", "source_path", "page_num",
                 "chunk_to_retrieve", "image_uri"],
        num_results=20,
        query_type="HYBRID",
        reranker=DatabricksReranker(["chunk_to_retrieve"]),
    )
```

- **Docs:** [Hybrid keyword + vector search](https://docs.databricks.com/aws/en/generative-ai/create-query-vector-search#hybrid-keyword-and-similarity-search) · [Reranking results](https://docs.databricks.com/aws/en/generative-ai/vector-search-reranker)

### Agent: Streaming LLM with Citations
- LLM call via `AsyncDatabricksOpenAI` (OpenAI-compatible Foundation Model API) against `databricks-claude-sonnet-4-5`
- Tokens stream as `response.output_text.delta` events; the final `response.output_item.done` carries `custom_outputs.citations` + `trace_id`
- Citations come straight from VS chunks (chunk_id, doc_id, page_num, snippet, score). NOT parsed from LLM prose. First-class structured data the UI and eval read directly.

```python
from databricks_openai import AsyncDatabricksOpenAI
client = AsyncDatabricksOpenAI()  # App SP

stream_resp = await client.chat.completions.create(
    model="databricks-claude-sonnet-4-5",
    messages=[
        {"role": "system", "content": CFG.llm.system_prompt},
        {"role": "user",   "content": f"Question: {query}\n\nRetrieved excerpts:\n{context}"},
    ],
    stream=True, temperature=0.0, max_tokens=2048,
)
async for chunk in stream_resp:
    if chunk.choices and chunk.choices[0].delta.content:
        yield chunk.choices[0].delta.content
```

- **Docs:** [Foundation Model APIs](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/) · [Query a chat completion model](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/query-foundation-model-apis)

### Agent: Auth Pattern (App SP, NOT OBO)

> [!IMPORTANT]
> Both the Vector Search SDK and the Foundation Model API check for **legacy OAuth scopes** (`all-apis` and `model-serving` respectively). Those scopes are NOT declarable in the Apps `user_authorization.scopes` block. OBO tokens fail with `Provided OAuth token does not have required scopes: all-apis` / `model-serving`.

- v3 uses **App SP** (auto-injected `DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET`) for VS, LLM, Lakebase, UC writes
- End-user attribution preserved separately via `mlflow.update_current_trace(metadata={...})`. Trace shows the user; downstream call principal is SP.
- App SP needs explicit grants on: VS index (`SELECT`), source table (`SELECT`), Volume (`READ VOLUME`), UC catalog/schema, all four OTel tables (`MODIFY, SELECT`), SQL warehouse (`CAN USE`), Lakebase Postgres role

- **Docs:** [Best practices for Databricks Apps](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/best-practices) · [Authorization in Databricks Apps](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth)

### MLflow Tracing → Unity Catalog
- One experiment `/Shared/contract_research_assistant` writes traces to UC OTel tables (`<catalog>.<schema>.<prefix>_otel_*`)
- Set up at module import via `set_experiment(experiment_name=..., trace_location=UnityCatalog(...))`
- `mlflow.openai.autolog()` instruments the LLM client. Each `/invocations` request becomes one trace with nested CHAT_MODEL + TOOL spans.

> [!WARNING]
> SP must have `MODIFY, SELECT` on ALL FOUR OTel tables: `_otel_spans`, `_otel_logs`, `_otel_annotations`, `_otel_metrics`. Missing one and the trace_location tags silently don't attach to the experiment, so traces fall back to the default MLflow store and never reach UC.

```python
from mlflow.entities.trace_location import UnityCatalog

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(
    experiment_name="/Shared/contract_research_assistant",
    trace_location=UnityCatalog(
        catalog_name="jreber_knowledge_assistant_demo",
        schema_name="audit",
        table_prefix="ka_v3",  # historical name; tables are ka_v3_otel_*
    ),
)
mlflow.openai.autolog()
```

- **Docs:** [Store traces in Unity Catalog](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog) · [MLflow Tracing overview](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/)

### Feature: End-user Trace Attribution
- Apps proxy forwards the logged-in user's email in `X-Forwarded-Email`
- Each request tags the active trace with `mlflow.trace.user` metadata so MLflow UI's "filter by user" lights up
- `ka.first_message`, `ka.llm_endpoint`, `ka.vs_index` added as well for filterable trace metadata

```python
def _tag_trace(request):
    email = get_user_email()  # from X-Forwarded-Email
    mlflow.update_current_trace(metadata={
        "mlflow.trace.user": email,
        "ka.user":           email,
        "ka.first_message":  request.input[0].content[:140],
        "ka.llm_endpoint":   CFG.llm.endpoint,
        "ka.vs_index":       CFG.vector_index.name,
    })
```

- **Docs:** [Add metadata to traces](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/concepts/trace-metadata) · [Apps user identity headers](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth)

### Feature: Lakebase Chat History
- **Why Lakebase:** OLTP storage with scale-to-zero (~free idle). OAuth-rotated DB tokens. Per-user filtering enforced in app code via `WHERE user_email = %s`.
- `psycopg` pool with custom `OAuthConnection` class. Each new pooled connection fetches a fresh 1-hour DB token. `max_lifetime=2700` recycles connections 15 minutes before expiry to avoid handing out stale tokens.
- Two tables: `threads` (per-user conversation metadata, `id UUID`, `user_email`, `title`, timestamps) + `messages` (`thread_id`, `role`, `content`, `citations JSONB`, `trace_id`)

```python
import psycopg
from psycopg_pool import ConnectionPool
from databricks.sdk import WorkspaceClient

class OAuthConnection(psycopg.Connection):
    @classmethod
    def connect(cls, conninfo="", **kwargs):
        cred = WorkspaceClient().postgres.generate_database_credential(endpoint=ENDPOINT_NAME)
        kwargs["password"] = cred.token
        return super().connect(conninfo, **kwargs)

pool = ConnectionPool(
    conninfo=f"dbname={PGDATABASE} user={PGUSER} host={PGHOST} sslmode=require",
    connection_class=OAuthConnection,
    min_size=1, max_size=10,
    max_lifetime=2700,  # recycle before 1h OAuth expiry
    open=False,         # opened in FastAPI lifespan
)
```

- **Docs:** [Lakebase Autoscaling overview](https://docs.databricks.com/aws/en/oltp/) · [Connect to Lakebase via OAuth](https://docs.databricks.com/aws/en/oltp/connect/)

### Feature: User Feedback (MLflow Assessments)
- Thumbs up/down + optional free-text comment. Both flow through `mlflow.log_feedback()`.
- Writes an `Assessment` to the trace's annotations table with `source_type=HUMAN`, `source_id=email`, optional `rationale=comment`
- Lives next to traces in MLflow UI. Queryable from `<catalog>.<schema>.<prefix>_otel_annotations`.

```python
from mlflow.entities import AssessmentSource
from mlflow.entities.assessment_source import AssessmentSourceType

mlflow.log_feedback(
    trace_id=trace_id,
    name="user_feedback",
    value=(vote == "up"),
    source=AssessmentSource(
        source_type=AssessmentSourceType.HUMAN,
        source_id=user_email,
    ),
    rationale=comment,
)
```

- **Docs:** [Collect human feedback on traces](https://docs.databricks.com/aws/en/mlflow3/genai/human-feedback/) · [MLflow Assessments API](https://docs.databricks.com/aws/en/mlflow3/genai/human-feedback/concepts/assessments)

### Feature: In-App PDF Viewer
- Click a citation, side panel opens with the source PDF in the browser's native PDF viewer
- Backend route streams bytes from the UC Volume via `WorkspaceClient.files.download()`
- URL anchor `#page=N` jumps the viewer to the cited page automatically
- Path-validated against an allowlist prefix to prevent arbitrary Volume reads

```python
from fastapi.responses import Response

@router.get("/api/documents")
def get_document(path: str):
    _validate_path(path)  # allowlist: must start with the contracts Volume prefix
    data = ws.files.download(path).contents.read()  # PDFs <5 MB, read fully
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
```

- **Docs:** [Files API for Volumes](https://docs.databricks.com/aws/en/files/) · [`WorkspaceClient.files`](https://databricks-sdk-py.readthedocs.io/en/latest/workspace/files/files.html)

### Feature: Error Surfacing
- Agent errors (PermissionDenied, Timeout, FM API hiccup) bubble up as a `response.error` SSE event with a user-facing message + raw exception detail + trace_id
- Frontend renders a red error card in place of the assistant bubble. Expandable "show details" + monospace `trace_id` for support debugging.
- Errored responses don't get persisted to Lakebase chat history

```python
try:
    chunks = await retrieve(...)
    async for delta in _stream_tokens(...): ...
except Exception as e:
    yield ResponsesAgentStreamEvent(
        type="response.error",
        error={
            "message":  _classify_error(e),
            "detail":   f"{type(e).__name__}: {e}"[:500],
            "trace_id": _current_trace_id(),
        },
    )
```

### Supervisor Agent Scaffold (stub, off by default)
- `server/supervisor.py` ships a fully-written LLM-as-judge groundedness scorer
- Off by default. Set `KA_ENABLE_SUPERVISOR=true` to wire it in.
- When active: after `@stream` completes, a background `asyncio.create_task(judge_response(...))` runs a second LLM call to score the answer 0-1 against the retrieved chunks. Writes the score as an MLflow Assessment with `source_type=LLM_JUDGE`.
- Why stub: untuned judge prompt + 2x LLM cost. Belongs behind a calibrated eval set before going active.

```python
mlflow.log_feedback(
    trace_id=trace_id,
    name="groundedness",
    value=score,  # 0.0 - 1.0
    source=AssessmentSource(
        source_type=AssessmentSourceType.LLM_JUDGE,
        source_id="databricks-claude-sonnet-4-5",
    ),
    rationale=rationale,
)
```
