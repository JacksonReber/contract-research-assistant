# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Ingest PDFs to Volume + raw_contracts manifest
# MAGIC
# MAGIC Self-bootstraps the Unity Catalog catalog, default + audit schemas, and
# MAGIC contracts Volume on first run.
# MAGIC
# MAGIC **Reads:** local PDFs under `../data/cuad/` and `../data/synthetic/` (relative to this notebook in the Git Folder).
# MAGIC **Writes:** `/Volumes/{catalog}/{schema}/{volume}/raw/` + `{catalog}.{schema}.raw_contracts`.
# MAGIC **Idempotent:** yes — MERGE on sha256.

# COMMAND ----------
dbutils.widgets.text("catalog", "jreber_knowledge_assistant_demo")
dbutils.widgets.text("schema", "default")
dbutils.widgets.text("volume", "contracts")
dbutils.widgets.text("audit_schema", "audit")
dbutils.widgets.text("source_root", "/Workspace/Users/jackson.reber@databricks.com/Demos/knowledge-assistant-demo/data")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
audit_schema = dbutils.widgets.get("audit_schema")
source_root = dbutils.widgets.get("source_root")

# COMMAND ----------
# MAGIC %md ## Bootstrap UC: catalog, schemas, volume

# COMMAND ----------
spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{audit_schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{volume}")
print(f"Catalog: {catalog}")
print(f"Schemas: {schema}, {audit_schema}")
print(f"Volume:  {catalog}.{schema}.{volume}")

# COMMAND ----------
# MAGIC %md ## Helpers

# COMMAND ----------
import hashlib
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

volume_raw = f"/Volumes/{catalog}/{schema}/{volume}/raw"
Path(volume_raw).mkdir(parents=True, exist_ok=True)


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def refine_source_type(coarse: str, filename: str) -> str:
    if coarse == "cuad":
        return "cuad"
    if filename.startswith("MSSA-"):
        return "synthetic_mssa"
    if filename.startswith("SOW-"):
        return "synthetic_sow"
    if filename.startswith("CO-"):
        return "synthetic_co"
    return "synthetic_other"


# COMMAND ----------
# MAGIC %md ## Copy PDFs into the Volume and build the row set

# COMMAND ----------
rows = []
for coarse, subdir in [("cuad", "cuad"), ("synthetic", "synthetic")]:
    src = Path(source_root) / subdir
    if not src.exists():
        print(f"  WARN: {src} does not exist; skipping")
        continue
    pdfs = sorted(src.glob("*.pdf"))
    print(f"  {coarse}: {len(pdfs)} PDFs from {src}")
    for pdf in pdfs:
        digest = sha256_of(str(pdf))
        dest = f"{volume_raw}/{pdf.name}"
        # Files-in-Workspace and Volume paths both support standard Python file IO.
        shutil.copyfile(str(pdf), dest)
        rows.append({
            "doc_id": pdf.stem,
            "filename": pdf.name,
            "path": dest,
            "source_type": refine_source_type(coarse, pdf.name),
            "sha256": digest,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        })

print(f"Staged {len(rows)} PDFs in {volume_raw}")

# COMMAND ----------
# MAGIC %md ## MERGE into raw_contracts

# COMMAND ----------
import pandas as pd

target = f"{catalog}.{schema}.raw_contracts"
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {target} (
    doc_id STRING,
    filename STRING,
    path STRING,
    source_type STRING,
    sha256 STRING,
    ingested_at STRING
) USING DELTA
""")

if rows:
    sdf = spark.createDataFrame(pd.DataFrame(rows))
    sdf.createOrReplaceTempView("incoming")
    spark.sql(f"""
    MERGE INTO {target} t
    USING incoming s
    ON t.sha256 = s.sha256
    WHEN NOT MATCHED THEN INSERT *
    """)
else:
    print("No rows to merge.")

# COMMAND ----------
# MAGIC %md ## Audit log

# COMMAND ----------
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog}.{audit_schema}.runs (
    run_id STRING,
    component STRING,
    started_at STRING,
    finished_at STRING,
    status STRING,
    error_msg STRING,
    rows_in BIGINT,
    rows_out BIGINT
) USING DELTA
""")

audit_row = [{
    "run_id": f"00_ingest_{int(time.time())}",
    "component": "00_ingest",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "status": "success",
    "error_msg": None,
    "rows_in": len(rows),
    "rows_out": spark.table(target).count(),
}]
spark.createDataFrame(pd.DataFrame(audit_row)).write.mode("append").saveAsTable(
    f"{catalog}.{audit_schema}.runs"
)

# COMMAND ----------
# MAGIC %md ## Verify

# COMMAND ----------
display(spark.table(target).groupBy("source_type").count())
