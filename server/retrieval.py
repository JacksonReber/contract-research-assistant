"""Vector Search hybrid retrieval with OBO-aware auth.

Mirrors the auth resolution in `server.auth`: OBO from Apps proxy → dev token
→ ambient SDK auth. VS client is sync; `retrieve()` wraps it in `to_thread`
so the async `@invoke()` / `@stream()` handlers don't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from databricks.vector_search.client import VectorSearchClient
from databricks.vector_search.reranker import DatabricksReranker
from mlflow.genai.agent_server import get_request_headers

from server.config import RetrievalConfig, VectorIndexConfig

logger = logging.getLogger(__name__)


def _resolve_obo_token() -> str | None:
  headers = get_request_headers() or {}
  return headers.get('x-forwarded-access-token') or headers.get('X-Forwarded-Access-Token')


def _make_vs_client() -> VectorSearchClient:
  """Resolve VS client credentials.

  **Important:** VS SDK requires the legacy `all-apis` OAuth scope. OBO tokens
  scoped to `vectorsearch.vector-search-endpoints` are REJECTED with
  `Provided OAuth token does not have required scopes: all-apis`. So for VS
  specifically we prefer App SP credentials (which carry `all-apis`) over OBO,
  even though the rest of the agent runs as OBO. Acceptable for shared-corpus
  chat — the same VS index is queried regardless of which user asked.
  """
  host = os.environ.get('DATABRICKS_HOST', '').rstrip('/')
  if host and not host.startswith('http'):
    host = f'https://{host}'

  # In Databricks Apps the runtime injects DATABRICKS_CLIENT_ID + _SECRET for
  # the App SP. Prefer that for VS regardless of whether an OBO token is
  # present.
  sp_id = os.environ.get('DATABRICKS_CLIENT_ID')
  sp_secret = os.environ.get('DATABRICKS_CLIENT_SECRET')
  if sp_id and sp_secret and host:
    return VectorSearchClient(
      workspace_url=host,
      service_principal_client_id=sp_id,
      service_principal_client_secret=sp_secret,
      disable_notice=True,
    )

  # Local dev: use dev token (PAT-style).
  dev = os.environ.get('DATABRICKS_TOKEN')
  if dev and host:
    return VectorSearchClient(
      workspace_url=host, personal_access_token=dev, disable_notice=True
    )

  # Last-resort fallback to ambient SDK auth (rarely hit).
  return VectorSearchClient(disable_notice=True)


def _search_sync(
  vi: VectorIndexConfig, ret: RetrievalConfig, query: str
) -> list[dict[str, Any]]:
  client = _make_vs_client()
  index = client.get_index(endpoint_name=vi.endpoint, index_name=vi.name)
  result = index.similarity_search(
    query_text=query,
    columns=vi.columns,
    num_results=ret.num_results,
    query_type=ret.query_type,
    reranker=DatabricksReranker(['chunk_to_retrieve']),
  )
  rows = (result.get('result') or {}).get('data_array') or []
  out: list[dict[str, Any]] = []
  for row in rows:
    if not row:
      continue
    score = row[-1] if len(row) > len(vi.columns) else None
    mapping = dict(zip(vi.columns, row[: len(vi.columns)]))
    mapping['score'] = score
    out.append(mapping)
  return out


async def retrieve(
  vi: VectorIndexConfig, ret: RetrievalConfig, query: str
) -> list[dict[str, Any]]:
  """Async wrapper — VS SDK is sync, run in threadpool."""
  return await asyncio.to_thread(_search_sync, vi, ret, query)
