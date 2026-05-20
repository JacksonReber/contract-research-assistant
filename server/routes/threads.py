"""REST endpoints for chat thread + message persistence.

Auth model: App SP writes (or local user in dev); rows tagged with
`user_email` from `X-Forwarded-Email`. Per-user filtering enforced by
`WHERE user_email = %s` on every query.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from server.db import pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/threads')


def _user_email(request: Request) -> str:
  """Pull end-user email from Apps proxy header; fall back to 'local-dev'."""
  email = (
    request.headers.get('x-forwarded-email')
    or request.headers.get('X-Forwarded-Email')
    or request.headers.get('x-forwarded-user')
    or request.headers.get('X-Forwarded-User')
  )
  return email or 'local-dev'


def _require_pool():
  if pool is None:
    raise HTTPException(503, 'Lakebase not configured — chat history disabled')


# --- request/response models ---

class ThreadSummary(BaseModel):
  id: str
  title: str
  created_at: str
  updated_at: str


class MessageOut(BaseModel):
  id: str
  role: str
  content: str
  citations: list[dict[str, Any]] | None = None
  trace_id: str | None = None
  created_at: str


class ThreadDetail(BaseModel):
  id: str
  title: str
  created_at: str
  updated_at: str
  messages: list[MessageOut]


class CreateThreadIn(BaseModel):
  title: str | None = None


class RenameThreadIn(BaseModel):
  title: str = Field(min_length=1, max_length=200)


class AppendMessageIn(BaseModel):
  role: str = Field(pattern='^(user|assistant)$')
  content: str
  citations: list[dict[str, Any]] | None = None
  trace_id: str | None = None


# --- routes ---

@router.get('', response_model=list[ThreadSummary])
def list_threads(request: Request):
  _require_pool()
  user = _user_email(request)
  with pool.connection() as conn, conn.cursor() as cur:  # type: ignore[union-attr]
    cur.execute(
      'SELECT id, title, created_at, updated_at FROM threads '
      'WHERE user_email = %s ORDER BY updated_at DESC LIMIT 100',
      (user,),
    )
    return [
      ThreadSummary(
        id=str(r[0]),
        title=r[1],
        created_at=r[2].isoformat(),
        updated_at=r[3].isoformat(),
      )
      for r in cur.fetchall()
    ]


@router.post('', response_model=ThreadSummary)
def create_thread(payload: CreateThreadIn, request: Request):
  _require_pool()
  user = _user_email(request)
  title = (payload.title or 'New chat').strip()[:200] or 'New chat'
  with pool.connection() as conn, conn.cursor() as cur:  # type: ignore[union-attr]
    cur.execute(
      'INSERT INTO threads (user_email, title) VALUES (%s, %s) '
      'RETURNING id, title, created_at, updated_at',
      (user, title),
    )
    row = cur.fetchone()
    conn.commit()
  return ThreadSummary(
    id=str(row[0]), title=row[1], created_at=row[2].isoformat(), updated_at=row[3].isoformat()
  )


@router.get('/{thread_id}', response_model=ThreadDetail)
def get_thread(thread_id: UUID, request: Request):
  _require_pool()
  user = _user_email(request)
  with pool.connection() as conn, conn.cursor() as cur:  # type: ignore[union-attr]
    cur.execute(
      'SELECT id, title, created_at, updated_at FROM threads '
      'WHERE id = %s AND user_email = %s',
      (str(thread_id), user),
    )
    row = cur.fetchone()
    if not row:
      raise HTTPException(404, 'thread not found')
    thread = ThreadSummary(
      id=str(row[0]),
      title=row[1],
      created_at=row[2].isoformat(),
      updated_at=row[3].isoformat(),
    )
    cur.execute(
      'SELECT id, role, content, citations, trace_id, created_at FROM messages '
      'WHERE thread_id = %s ORDER BY created_at ASC',
      (str(thread_id),),
    )
    messages = [
      MessageOut(
        id=str(r[0]),
        role=r[1],
        content=r[2],
        citations=r[3],
        trace_id=r[4],
        created_at=r[5].isoformat(),
      )
      for r in cur.fetchall()
    ]
  return ThreadDetail(**thread.model_dump(), messages=messages)


@router.post('/{thread_id}/messages', response_model=MessageOut)
def append_message(thread_id: UUID, payload: AppendMessageIn, request: Request):
  _require_pool()
  user = _user_email(request)
  with pool.connection() as conn, conn.cursor() as cur:  # type: ignore[union-attr]
    cur.execute(
      'SELECT 1 FROM threads WHERE id = %s AND user_email = %s',
      (str(thread_id), user),
    )
    if cur.fetchone() is None:
      raise HTTPException(404, 'thread not found')

    cur.execute(
      'INSERT INTO messages (thread_id, role, content, citations, trace_id) '
      'VALUES (%s, %s, %s, %s::jsonb, %s) '
      'RETURNING id, role, content, citations, trace_id, created_at',
      (
        str(thread_id),
        payload.role,
        payload.content,
        json.dumps(payload.citations) if payload.citations is not None else None,
        payload.trace_id,
      ),
    )
    row = cur.fetchone()
    cur.execute(
      'UPDATE threads SET updated_at = now() WHERE id = %s',
      (str(thread_id),),
    )
    conn.commit()
  return MessageOut(
    id=str(row[0]),
    role=row[1],
    content=row[2],
    citations=row[3],
    trace_id=row[4],
    created_at=row[5].isoformat(),
  )


@router.patch('/{thread_id}', response_model=ThreadSummary)
def rename_thread(thread_id: UUID, payload: RenameThreadIn, request: Request):
  _require_pool()
  user = _user_email(request)
  with pool.connection() as conn, conn.cursor() as cur:  # type: ignore[union-attr]
    cur.execute(
      'UPDATE threads SET title = %s, updated_at = now() '
      'WHERE id = %s AND user_email = %s '
      'RETURNING id, title, created_at, updated_at',
      (payload.title.strip()[:200], str(thread_id), user),
    )
    row = cur.fetchone()
    if not row:
      raise HTTPException(404, 'thread not found')
    conn.commit()
  return ThreadSummary(
    id=str(row[0]), title=row[1], created_at=row[2].isoformat(), updated_at=row[3].isoformat()
  )


@router.delete('/{thread_id}')
def delete_thread(thread_id: UUID, request: Request):
  _require_pool()
  user = _user_email(request)
  with pool.connection() as conn, conn.cursor() as cur:  # type: ignore[union-attr]
    cur.execute(
      'DELETE FROM threads WHERE id = %s AND user_email = %s',
      (str(thread_id), user),
    )
    if cur.rowcount == 0:
      raise HTTPException(404, 'thread not found')
    conn.commit()
  return {'deleted': str(thread_id)}
