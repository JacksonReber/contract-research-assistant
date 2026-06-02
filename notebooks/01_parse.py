# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Parse PDFs with ai_parse_document (multi-modal)
# MAGIC
# MAGIC **Reads:** binary files from `/Volumes/{catalog}/{schema}/{volume}/raw/`
# MAGIC **Writes:** `{catalog}.{schema}.parsed_contracts` (one row per source PDF, with `parsed` VARIANT)
# MAGIC
# MAGIC Multi-modal is enabled by passing `imageOutputPath` to `ai_parse_document`.
# MAGIC Output images land in `/Volumes/{catalog}/{schema}/{volume}/page_images/` and are
# MAGIC referenced via `image_uri` in the parsed VARIANT for downstream multi-modal retrieval.
# MAGIC
# MAGIC **Compute requirement:** DBR 17.1+ (ai_parse_document availability).

# COMMAND ----------
dbutils.widgets.text("catalog", "jreber_knowledge_assistant_demo")
dbutils.widgets.text("schema", "default")
dbutils.widgets.text("volume", "contracts")
dbutils.widgets.text("audit_schema", "audit")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
audit_schema = dbutils.widgets.get("audit_schema")

raw_volume_path = f"/Volumes/{catalog}/{schema}/{volume}/raw"
images_volume_path = f"/Volumes/{catalog}/{schema}/{volume}/page_images"
parsed_table = f"{catalog}.{schema}.parsed_contracts"
raw_table = f"{catalog}.{schema}.raw_contracts"

# COMMAND ----------
# MAGIC %md ## Parse PDFs

# COMMAND ----------
from pyspark.sql.functions import expr, current_timestamp, col, input_file_name

# Read PDFs as binary, run ai_parse_document (text-only — image extraction
# disabled: serverless image upload hits RESOURCE_EXHAUSTED and sets an
# error_status that drops the doc at the chunk step. The PDF viewer opens the
# source PDF by page, so extracted page images aren't needed.)
binary_df = (
    spark.read.format("binaryFile")
    .option("pathGlobFilter", "*.pdf")
    .option("recursiveFileLookup", "true")
    .load(raw_volume_path)
)

parsed_df = (
    binary_df
    .withColumn(
        "parsed",
        expr("ai_parse_document(content)"),
    )
    .withColumn("parsed_at", current_timestamp())
    .select("path", "parsed", "parsed_at")
)

# COMMAND ----------
# MAGIC %md ## Join back to raw_contracts to get doc_id, write parsed_contracts

# COMMAND ----------
raw_df = spark.table(raw_table).select("doc_id", "path", "source_type")

# Note: binaryFile path uses "dbfs:" prefix sometimes; normalize before joining.
parsed_df = parsed_df.withColumn("path", expr("regexp_replace(path, '^dbfs:', '')"))

joined = (
    parsed_df.join(raw_df, on="path", how="left")
    .select("doc_id", "path", "source_type", "parsed", "parsed_at")
)

joined.write.mode("overwrite").saveAsTable(parsed_table)

# COMMAND ----------
# MAGIC %md ## Flag rows where ai_parse_document set an error_status

# COMMAND ----------
n_total = spark.table(parsed_table).count()
n_err = (
    spark.table(parsed_table)
    .filter("try_cast(parsed:error_status AS STRING) IS NOT NULL")
    .count()
)
print(f"Parsed {n_total} docs; {n_err} flagged with error_status")

# COMMAND ----------
# MAGIC %md ## Audit log

# COMMAND ----------
import time
from datetime import datetime, timezone
import pandas as pd

audit_row = [{
    "run_id": f"01_parse_{int(time.time())}",
    "component": "01_parse",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "status": "success" if n_err == 0 else "partial",
    "error_msg": f"{n_err} docs had error_status" if n_err else None,
    "rows_in": spark.table(raw_table).count(),
    "rows_out": n_total,
}]
spark.createDataFrame(pd.DataFrame(audit_row)).write.mode("append").saveAsTable(
    f"{catalog}.{audit_schema}.runs"
)

# COMMAND ----------
# MAGIC %md ## Sanity check — show parsed structure for one doc

# COMMAND ----------
display(
    spark.table(parsed_table)
    .selectExpr(
        "doc_id",
        "source_type",
        "try_cast(parsed:error_status AS STRING) AS error_status",
        "size(try_cast(parsed:document:elements AS ARRAY<VARIANT>)) AS n_elements",
    )
    .limit(10)
)
