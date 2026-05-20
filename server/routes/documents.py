"""Serve PDFs from the source UC Volume for in-app rendering.

Reads bytes via `WorkspaceClient.files.download()` using the user's OBO token
(per-user Volume ACLs enforced). Streams `application/pdf` inline so the
browser's native PDF viewer renders it inside an iframe.

Security: path must start with one of `ALLOWED_VOLUME_PREFIXES` to prevent
arbitrary file reads.
"""

from __future__ import annotations

import logging
import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from server.auth import get_user_workspace_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/documents')

# Comma-separated env var; defaults to the v3 contracts volume.
ALLOWED_VOLUME_PREFIXES = [
  p.strip()
  for p in os.getenv(
    'KA_ALLOWED_VOLUME_PREFIXES',
    '/Volumes/jreber_knowledge_assistant_demo/default/contracts/',
  ).split(',')
  if p.strip()
]


def _validate_path(path: str) -> None:
  if not path or '..' in path or not path.startswith('/Volumes/'):
    raise HTTPException(400, 'invalid path')
  if not any(path.startswith(p) for p in ALLOWED_VOLUME_PREFIXES):
    raise HTTPException(403, 'path outside allowed volumes')


@router.get('')
def get_document(path: str):
  _validate_path(path)
  ws = get_user_workspace_client()
  try:
    download = ws.files.download(path)
    # Read whole file into memory — contracts are <5 MB and `download.contents`
    # is closed when the route returns, which truncates a StreamingResponse
    # mid-transfer.
    data = download.contents.read()
  except Exception as e:  # noqa: BLE001
    msg = str(e)
    if 'not found' in msg.lower() or '404' in msg:
      raise HTTPException(404, 'not found') from e
    logger.exception('files.download failed for %s', path)
    raise HTTPException(502, f'volume read failed: {msg[:200]}') from e

  filename = re.sub(r'[^\w.\- ]', '_', os.path.basename(path)) or 'document.pdf'
  media_type = 'application/pdf' if filename.lower().endswith('.pdf') else 'application/octet-stream'

  return Response(
    content=data,
    media_type=media_type,
    headers={
      'Content-Disposition': f'inline; filename="{filename}"',
      'Cache-Control': 'private, max-age=300',
    },
  )
