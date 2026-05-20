"""FastAPI entrypoint.

Layers:
- `mlflow.genai.agent_server.AgentServer` registers POST /invocations
  (streaming + non-streaming based on body `stream: true`) plus GET /info, /health.
- We add GET /api/config (public view of agent_config.yaml) and GET /api/whoami
  (diagnostic for OBO scope verification).
- Static SPA fallback so the React app is reachable at /.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mlflow.genai.agent_server import AgentServer

# Importing server.agent registers the @invoke / @stream handlers.
import server.agent  # noqa: F401
from server.config import load_agent_config
from server.db import pool as db_pool
from server.routes.documents import router as documents_router
from server.routes.feedback import router as feedback_router
from server.routes.threads import router as threads_router

logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

agent_server = AgentServer('ResponsesAgent', enable_chat_proxy=False)
app = agent_server.app
app.include_router(threads_router)
app.include_router(feedback_router)
app.include_router(documents_router)


@app.on_event('startup')
def _open_pool() -> None:
  if db_pool is not None:
    try:
      db_pool.open(wait=True, timeout=30.0)
      logger.info('Lakebase connection pool opened.')
    except Exception:  # noqa: BLE001
      logger.exception('Failed to open Lakebase pool — chat history disabled.')


@app.on_event('shutdown')
def _close_pool() -> None:
  if db_pool is not None:
    try:
      db_pool.close()
    except Exception:  # noqa: BLE001
      logger.debug('Pool close error (non-fatal)', exc_info=True)


@app.get('/api/config')
async def api_config() -> dict:
  return load_agent_config().public_view()


@app.get('/api/whoami')
async def api_whoami(request: Request) -> dict:
  """Diagnostic: returns headers + decoded JWT scopes for OBO verification."""
  import base64
  import json as _json

  hdrs = {k: v for k, v in request.headers.items()}
  token = hdrs.get('x-forwarded-access-token') or hdrs.get('X-Forwarded-Access-Token')
  scope_info: dict = {'has_token': bool(token)}
  if token:
    try:
      parts = token.split('.')
      if len(parts) == 3:
        pad = '=' * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        scope_info['scope'] = payload.get('scope')
        scope_info['sub'] = payload.get('sub')
        scope_info['client_id'] = payload.get('client_id')
        scope_info['aud'] = payload.get('aud')
        scope_info['exp'] = payload.get('exp')
    except Exception as e:  # noqa: BLE001
      scope_info['decode_error'] = str(e)
  return {
    'forwarded_user': hdrs.get('x-forwarded-user') or hdrs.get('X-Forwarded-User'),
    'forwarded_email': hdrs.get('x-forwarded-email') or hdrs.get('X-Forwarded-Email'),
    'token': scope_info,
  }


# --- Static frontend ------------------------------------------------------------

CLIENT_DIR_CANDIDATES = [
  Path(__file__).parent.parent / 'client' / 'out',
  Path.cwd() / 'client' / 'out',
  Path('/app/python/source_code/client/out'),
]
_client_dir: Path | None = next((p for p in CLIENT_DIR_CANDIDATES if p.exists()), None)

if _client_dir is not None:
  logger.info('Serving static frontend from %s', _client_dir)
  if (_client_dir / 'assets').exists():
    app.mount(
      '/assets', StaticFiles(directory=str(_client_dir / 'assets')), name='assets'
    )

  @app.get('/')
  async def root() -> FileResponse:
    return FileResponse(str(_client_dir / 'index.html'))

  @app.get('/{full_path:path}')
  async def spa(full_path: str) -> FileResponse:
    reserved = ('invocations', 'info', 'health', 'api/', 'assets/')
    if any(full_path.startswith(r) for r in reserved):
      raise HTTPException(status_code=404)
    static_path = _client_dir / full_path
    if static_path.is_file():
      return FileResponse(str(static_path))
    return FileResponse(str(_client_dir / 'index.html'))
else:
  logger.info('No client/out directory found — frontend not mounted (dev mode).')


def main() -> None:
  agent_server.run(app_import_string='server.start_server:app')


if __name__ == '__main__':
  main()
