# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Chunk via ai_prep_search + create Delta-Sync Vector Search index
# MAGIC
# MAGIC **Reads:** `{catalog}.{schema}.parsed_contracts`
# MAGIC **Writes:** `{catalog}.{schema}.search_ready` + Vector Search index `{catalog}.{schema}.contracts_idx`
# MAGIC
# MAGIC `ai_prep_search` takes the VARIANT from `ai_parse_document` and emits a structured
# MAGIC chunk array with `chunk_id`, `chunk_position`, `chunk_to_retrieve` (raw text shown to users),
# MAGIC and `chunk_to_embed` (context-enriched text used for embedding). When the source parse
# MAGIC was done with `imageOutputPath`, each chunk also carries `image_uri` references for
# MAGIC multi-modal retrieval.
# MAGIC
# MAGIC The Vector Search index uses **managed embeddings** (`databricks-gte-large-en`, 1024 dim)
# MAGIC keyed on `chunk_to_embed` — we don't compute embeddings ourselves.

# COMMAND ----------
# MAGIC %pip install databricks-vectorsearch>=0.40 -q

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "jreber_knowledge_assistant_demo")
dbutils.widgets.text("schema", "default")
dbutils.widgets.text("audit_schema", "audit")
dbutils.widgets.text("vs_endpoint", "one-env-shared-endpoint-11")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
audit_schema = dbutils.widgets.get("audit_schema")
vs_endpoint = dbutils.widgets.get("vs_endpoint")

parsed_table = f"{catalog}.{schema}.parsed_contracts"
search_table = f"{catalog}.{schema}.search_ready"
index_name = f"{catalog}.{schema}.contracts_idx"

# COMMAND ----------
# MAGIC %md ## Chunk parsed_contracts → search_ready

# COMMAND ----------
spark.sql(f"""
CREATE OR REPLACE TABLE {search_table} AS
WITH prepped AS (
  SELECT
    doc_id,
    source_type,
    path AS source_path,
    ai_prep_search(parsed) AS prep
  FROM {parsed_table}
  WHERE try_cast(parsed:error_status AS STRING) IS NULL
),
chunks AS (
  SELECT
    doc_id,
    source_type,
    source_path,
    explode(variant_get(prep, '$.document.contents', 'ARRAY<VARIANT>')) AS chunk
  FROM prepped
)
SELECT
  concat(doc_id, '__', cast(variant_get(chunk, '$.chunk_position', 'INT') AS STRING)) AS chunk_id,
  doc_id,
  source_type,
  source_path,
  cast(variant_get(chunk, '$.chunk_position', 'INT') AS INT) AS chunk_position,
  cast(variant_get(chunk, '$.chunk_to_retrieve', 'STRING') AS STRING) AS chunk_to_retrieve,
  cast(variant_get(chunk, '$.chunk_to_embed', 'STRING') AS STRING) AS chunk_to_embed,
  cast(variant_get(chunk, '$.pages[0].image_uri', 'STRING') AS STRING) AS image_uri,
  cast(variant_get(chunk, '$.pages[0].page_id', 'INT') AS INT) AS page_num
FROM chunks
WHERE variant_get(chunk, '$.chunk_to_retrieve', 'STRING') IS NOT NULL
  AND length(trim(cast(variant_get(chunk, '$.chunk_to_retrieve', 'STRING') AS STRING))) > 10
""")

# Required for Delta-Sync indexing
spark.sql(f"ALTER TABLE {search_table} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")

n_chunks = spark.table(search_table).count()
print(f"Created {n_chunks} chunks in {search_table}")

# COMMAND ----------
# MAGIC %md ## Create / refresh Delta-Sync Vector Search index

# COMMAND ----------
from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient(disable_notice=True)

# Drop existing index for dev iteration (matches the dev-mode contract documented in CLAUDE.md)
try:
    existing = vsc.get_index(endpoint_name=vs_endpoint, index_name=index_name)
    print(f"Existing index found; deleting for clean re-create")
    vsc.delete_index(endpoint_name=vs_endpoint, index_name=index_name)
except Exception as e:
    print(f"No existing index (or could not get): {e}")

idx = vsc.create_delta_sync_index(
    endpoint_name=vs_endpoint,
    source_table_name=search_table,
    index_name=index_name,
    pipeline_type="TRIGGERED",
    primary_key="chunk_id",
    embedding_source_column="chunk_to_embed",
    embedding_model_endpoint_name="databricks-gte-large-en",
)
print(f"Index creation kicked off: {index_name}")

# COMMAND ----------
# MAGIC %md ## Poll for index online

# COMMAND ----------
import time

deadline = time.time() + 1800  # 30 min
while time.time() < deadline:
    desc = vsc.get_index(endpoint_name=vs_endpoint, index_name=index_name).describe()
    status = desc.get("status", {})
    ready = status.get("ready", False)
    detailed = status.get("detailed_state", "")
    print(f"  ready={ready} detailed={detailed}")
    if ready and "ONLINE" in detailed:
        break
    time.sleep(30)
else:
    raise RuntimeError(f"Index {index_name} did not reach ONLINE within 30 minutes")

# COMMAND ----------
# MAGIC %md ## Quick query check

# COMMAND ----------
idx = vsc.get_index(endpoint_name=vs_endpoint, index_name=index_name)
res = idx.similarity_search(
    query_text="termination notice period",
    columns=["chunk_id", "doc_id", "chunk_to_retrieve"],
    num_results=5,
)
for r in res.get("result", {}).get("data_array", []):
    print(r)

# COMMAND ----------
# MAGIC %md ## Audit log

# COMMAND ----------
from datetime import datetime, timezone
import pandas as pd

audit_row = [{
    "run_id": f"02_chunk_index_{int(time.time())}",
    "component": "02_chunk_index",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "status": "success",
    "error_msg": None,
    "rows_in": spark.table(parsed_table).count(),
    "rows_out": n_chunks,
}]
spark.createDataFrame(pd.DataFrame(audit_row)).write.mode("append").saveAsTable(
    f"{catalog}.{audit_schema}.runs"
)
