"""Lakebase Postgres connection pool with OAuth token refresh.

Per the databricks-app-python skill: `OAuthConnection.connect()` is called
by the pool when it creates a new connection, so a fresh token is fetched
each time. `max_lifetime=2700` recycles connections before the 1-hour token
expires.

In Databricks Apps with a Database resource attached, PGHOST/PGUSER/PGPORT/
PGDATABASE are auto-injected. For autoscaling Lakebase we set them explicitly
in app.yaml + ENDPOINT_NAME.

The pool is created with `open=False` and explicitly opened in FastAPI's
lifespan hook so the app fails fast if the DB is unreachable.

If `ENDPOINT_NAME` (or `PGHOST`) is not configured, `pool` is None and
chat persistence is a no-op — agent + UI keep working, just no history.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg_pool import ConnectionPool

if TYPE_CHECKING:
  pass

logger = logging.getLogger(__name__)

_endpoint_name = os.environ.get('ENDPOINT_NAME', '').strip()
_pg_host = os.environ.get('PGHOST', '').strip()
_pg_user = os.environ.get('PGUSER', '').strip()
_pg_database = os.environ.get('PGDATABASE', 'databricks_postgres').strip()
_pg_port = os.environ.get('PGPORT', '5432').strip()
_pg_sslmode = os.environ.get('PGSSLMODE', 'require').strip()


class OAuthConnection(psycopg.Connection):
  """Fetch a fresh OAuth token each time the pool creates a new connection."""

  @classmethod
  def connect(cls, conninfo: str = '', **kwargs):  # type: ignore[override]
    w = WorkspaceClient()
    credential = w.postgres.generate_database_credential(endpoint=_endpoint_name)
    kwargs['password'] = credential.token
    return super().connect(conninfo, **kwargs)


def _build_pool() -> ConnectionPool | None:
  if not (_endpoint_name and _pg_host and _pg_user):
    logger.info(
      'Lakebase not configured (ENDPOINT_NAME=%r PGHOST=%r PGUSER=%r) — '
      'chat persistence disabled.',
      _endpoint_name, _pg_host, _pg_user,
    )
    return None
  conninfo = (
    f'dbname={_pg_database} user={_pg_user} host={_pg_host} '
    f'port={_pg_port} sslmode={_pg_sslmode}'
  )
  return ConnectionPool(
    conninfo=conninfo,
    connection_class=OAuthConnection,
    min_size=1,
    max_size=10,
    max_lifetime=2700,  # 45 min — recycle before 1-hour OAuth expiry
    open=False,         # opened in FastAPI lifespan; fail-fast there
  )


pool: ConnectionPool | None = _build_pool()


def is_configured() -> bool:
  return pool is not None
