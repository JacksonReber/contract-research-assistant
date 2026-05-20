"""Resolve the Databricks workspace client for outbound API calls.

OBO-first resolution order:
1. **OBO**: `X-Forwarded-Access-Token` header from the Databricks Apps proxy
   (per-user OAuth token). Per-user ACLs apply to every downstream call.
2. **Local dev**: `DATABRICKS_TOKEN` + `DATABRICKS_HOST` from `.env.local`.
3. **App SP fallback**: default `WorkspaceClient()` — picks up
   `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET` injected by Databricks Apps.
   Set `DISABLE_SP_FALLBACK=true` in production to surface auth misconfigurations
   loudly instead of silently falling back to SP.
"""

from __future__ import annotations

import logging
import os

from databricks.sdk import WorkspaceClient
from databricks_openai import AsyncDatabricksOpenAI
from mlflow.genai.agent_server import get_request_headers

logger = logging.getLogger(__name__)


def _resolve_obo_token() -> str | None:
  headers = get_request_headers() or {}
  return headers.get('x-forwarded-access-token') or headers.get('X-Forwarded-Access-Token')


def get_user_workspace_client() -> WorkspaceClient:
  host = os.environ.get('DATABRICKS_HOST', '').rstrip('/') or None

  obo = _resolve_obo_token()
  if obo and host:
    return WorkspaceClient(host=host, token=obo, auth_type='pat')

  dev = os.getenv('DATABRICKS_TOKEN')
  if dev and host:
    return WorkspaceClient(host=host, token=dev, auth_type='pat')

  if os.getenv('DISABLE_SP_FALLBACK', '').lower() in ('1', 'true', 'yes'):
    raise RuntimeError(
      'No OBO or dev token, and DISABLE_SP_FALLBACK is set. '
      'Cannot resolve a Databricks workspace client.'
    )
  logger.info('No OBO/dev token found; falling back to app service-principal credentials.')
  return WorkspaceClient()


def get_user_async_client() -> AsyncDatabricksOpenAI:
  return AsyncDatabricksOpenAI(workspace_client=get_user_workspace_client())


def get_app_async_client() -> AsyncDatabricksOpenAI:
  """Service-principal-scoped client. Used for non-user-scoped calls (e.g. writing
  feedback assessments, which the MLflow API only accepts from the SP token)."""
  return AsyncDatabricksOpenAI()


def get_user_email() -> str | None:
  headers = get_request_headers() or {}
  return (
    headers.get('x-forwarded-email')
    or headers.get('x-forwarded-user')
    or headers.get('X-Forwarded-Email')
    or headers.get('X-Forwarded-User')
  )
