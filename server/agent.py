"""KA agent — Apps-async port of the v2 ResponsesAgent.

Module-level `@invoke()` / `@stream()` async functions registered with
MLflow's `AgentServer`. Agent code runs inside the App process — no separate
Model Serving endpoint.

Pipeline (per request):
  1. Extract user query
  2. VS Hybrid retrieve (with DatabricksReranker) → chunks
  3. Build system + user messages with retrieved context
  4. Call LLM via AsyncDatabricksOpenAI (OBO-scoped)
     - @invoke: single non-streaming completion
     - @stream: token-by-token deltas
  5. Return ResponsesAgentResponse with custom_outputs.citations
"""

from __future__ import annotations

import logging
import os
from typing import Any, AsyncGenerator

import mlflow
from databricks_openai import AsyncDatabricksOpenAI
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
  ResponsesAgentRequest,
  ResponsesAgentResponse,
  ResponsesAgentStreamEvent,
)

from server.auth import get_user_email, get_user_workspace_client
from server.config import load_agent_config
from server.retrieval import retrieve

logger = logging.getLogger(__name__)


# --- MLflow tracing (UC-backed, configured day-one to avoid v2's sync gap) ---
_MLFLOW_TRACKING_URI = os.getenv('MLFLOW_TRACKING_URI', 'databricks')
_MLFLOW_EXPERIMENT_NAME = os.getenv('MLFLOW_EXPERIMENT_NAME', '/Shared/ka_v3_traces_uc')
_KA_TRACE_CATALOG = os.getenv('KA_TRACE_CATALOG', 'jreber_knowledge_assistant_demo')
_KA_TRACE_SCHEMA = os.getenv('KA_TRACE_SCHEMA', 'audit')
_KA_TRACE_TABLE_PREFIX = os.getenv('KA_TRACE_TABLE_PREFIX', 'ka_v3')

mlflow.set_tracking_uri(_MLFLOW_TRACKING_URI)
try:
  from mlflow.entities.trace_location import UnityCatalog

  exp = mlflow.set_experiment(
    experiment_name=_MLFLOW_EXPERIMENT_NAME,
    trace_location=UnityCatalog(
      catalog_name=_KA_TRACE_CATALOG,
      schema_name=_KA_TRACE_SCHEMA,
      table_prefix=_KA_TRACE_TABLE_PREFIX,
    ),
  )
  logger.info(
    'MLflow tracing → experiment %s (id=%s) → UC %s.%s.%s_otel_*',
    exp.name, exp.experiment_id, _KA_TRACE_CATALOG, _KA_TRACE_SCHEMA, _KA_TRACE_TABLE_PREFIX,
  )
except Exception as e:  # noqa: BLE001
  logger.warning(
    'Could not set UC-backed MLflow experiment %s (catalog=%s schema=%s): %s',
    _MLFLOW_EXPERIMENT_NAME, _KA_TRACE_CATALOG, _KA_TRACE_SCHEMA, e,
  )

mlflow.openai.autolog()

CFG = load_agent_config()


def _extract_query(request: ResponsesAgentRequest) -> str:
  for msg in reversed(request.input):
    role = getattr(msg, 'role', None) or (msg.get('role') if isinstance(msg, dict) else None)
    if role != 'user':
      continue
    content = (
      getattr(msg, 'content', None)
      if not isinstance(msg, dict)
      else msg.get('content')
    )
    if isinstance(content, str):
      return content
    if isinstance(content, list):
      for part in content:
        ptype = getattr(part, 'type', None) or (
          part.get('type') if isinstance(part, dict) else None
        )
        if ptype in ('input_text', 'text', 'output_text'):
          ptext = getattr(part, 'text', None) or (
            part.get('text') if isinstance(part, dict) else None
          )
          if ptext:
            return ptext
  return ''


def _tag_trace(request: ResponsesAgentRequest) -> None:
  """End-user attribution + agent metadata on the active MLflow trace."""
  try:
    metadata: dict[str, str] = {
      'ka.agent': CFG.name,
      'ka.llm_endpoint': CFG.llm.endpoint,
      'ka.vs_index': CFG.vector_index.name,
    }
    if email := get_user_email():
      metadata['mlflow.trace.user'] = email
      metadata['ka.user'] = email
    if request.input:
      first = request.input[0]
      content = getattr(first, 'content', None) or (
        first.get('content') if isinstance(first, dict) else None
      )
      if isinstance(content, str):
        metadata['ka.first_message'] = content[:140]
    mlflow.update_current_trace(metadata=metadata)
  except Exception:  # noqa: BLE001
    logger.debug('Could not tag trace', exc_info=True)


# --- Prompt + citation building ---------------------------------------------

def _build_messages(query: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
  context_blocks = [
    f"[doc_id={c.get('doc_id', '?')} page={c.get('page_num', '?')} "
    f"chunk_id={c.get('chunk_id', '?')}]\n{c.get('chunk_to_retrieve', '')}"
    for c in chunks
  ]
  context = (
    '\n\n---\n\n'.join(context_blocks) if context_blocks else '(no chunks retrieved)'
  )
  return [
    {'role': 'system', 'content': CFG.llm.system_prompt},
    {
      'role': 'user',
      'content': f'Question: {query}\n\nRetrieved excerpts:\n\n{context}',
    },
  ]


def _build_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
  return [
    {
      'chunk_id': c.get('chunk_id'),
      'doc_id': c.get('doc_id'),
      'source_type': c.get('source_type'),
      'source_path': c.get('source_path'),
      'page_num': c.get('page_num'),
      'snippet': (c.get('chunk_to_retrieve') or '')[:500],
      'image_uri': c.get('image_uri'),
      'score': c.get('score'),
    }
    for c in chunks
  ]


# --- LLM (SP via AsyncDatabricksOpenAI) -------------------------------------
# The Foundation Model API checks for the legacy `model-serving` OAuth scope.
# The scoped `serving.serving-endpoints` we can declare in app.yaml is rejected
# with `Provided OAuth token does not have required scopes: model-serving`.
# So we run LLM calls as the App SP. End-user attribution is preserved via
# `mlflow.trace.user` metadata in `_tag_trace`, not via the call identity.

def _llm_client() -> AsyncDatabricksOpenAI:
  return AsyncDatabricksOpenAI()


async def _generate(query: str, chunks: list[dict[str, Any]]) -> str:
  client = _llm_client()
  resp = await client.chat.completions.create(
    model=CFG.llm.endpoint,
    messages=_build_messages(query, chunks),
    temperature=CFG.llm.temperature,
    max_tokens=CFG.llm.max_tokens,
  )
  return resp.choices[0].message.content or ''


async def _stream_tokens(
  query: str, chunks: list[dict[str, Any]]
) -> AsyncGenerator[str, None]:
  client = _llm_client()
  stream_resp = await client.chat.completions.create(
    model=CFG.llm.endpoint,
    messages=_build_messages(query, chunks),
    temperature=CFG.llm.temperature,
    max_tokens=CFG.llm.max_tokens,
    stream=True,
  )
  async for chunk in stream_resp:
    if not chunk.choices:
      continue
    delta = chunk.choices[0].delta
    if delta and delta.content:
      yield delta.content


# --- AgentServer handlers ---------------------------------------------------

def _current_trace_id() -> str | None:
  """Best-effort capture of the active MLflow trace_id (for client-side feedback)."""
  try:
    span = mlflow.get_current_active_span()
    if span is not None:
      return getattr(span, 'request_id', None) or getattr(span, 'trace_id', None)
  except Exception:  # noqa: BLE001
    pass
  try:
    return mlflow.get_last_active_trace_id()
  except Exception:  # noqa: BLE001
    return None


def _classify_error(e: BaseException) -> str:
  """Map raw exceptions to a short user-facing label."""
  name = type(e).__name__
  msg = str(e)
  if 'PermissionDenied' in name or 'permission' in msg.lower() or '403' in msg:
    return 'Permission denied calling a downstream service.'
  if 'NotFound' in name or '404' in msg:
    return 'A required resource was not found.'
  if 'Timeout' in name or 'timed out' in msg.lower():
    return 'The request timed out.'
  return 'The agent ran into an unexpected error.'


@invoke()
async def _invoke(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
  _tag_trace(request)
  try:
    query = _extract_query(request)
    chunks = await retrieve(CFG.vector_index, CFG.retrieval, query)
    answer = await _generate(query, chunks)
    return ResponsesAgentResponse(
      output=[{
        'type': 'message',
        'id': 'msg_1',
        'role': 'assistant',
        'content': [{'type': 'output_text', 'text': answer}],
      }],
      custom_outputs={
        'citations': _build_citations(chunks),
        'trace_id': _current_trace_id(),
      },
    )
  except Exception as e:  # noqa: BLE001
    logger.exception('agent invoke failed')
    trace_id = _current_trace_id()
    user_msg = _classify_error(e)
    return ResponsesAgentResponse(
      output=[{
        'type': 'message',
        'id': 'msg_1',
        'role': 'assistant',
        'content': [{'type': 'output_text', 'text': user_msg}],
      }],
      custom_outputs={
        'citations': [],
        'trace_id': trace_id,
        'error': {
          'message': user_msg,
          'detail': f'{type(e).__name__}: {e}'[:500],
          'trace_id': trace_id,
        },
      },
    )


@stream()
async def _stream(
  request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
  _tag_trace(request)

  msg_id = 'msg_1'
  yield ResponsesAgentStreamEvent(
    type='response.output_item.added',
    item={'id': msg_id, 'type': 'message', 'role': 'assistant'},
    output_index=0,
  )

  full_text = ''
  query = ''
  chunks: list[dict[str, Any]] = []
  citations: list[dict[str, Any]] = []
  error_payload: dict[str, Any] | None = None

  try:
    query = _extract_query(request)
    chunks = await retrieve(CFG.vector_index, CFG.retrieval, query)
    citations = _build_citations(chunks)

    async for delta in _stream_tokens(query, chunks):
      full_text += delta
      yield ResponsesAgentStreamEvent(
        type='response.output_text.delta', item_id=msg_id, delta=delta
      )
  except Exception as e:  # noqa: BLE001
    logger.exception('agent stream failed')
    trace_id = _current_trace_id()
    user_msg = _classify_error(e)
    error_payload = {
      'message': user_msg,
      'detail': f'{type(e).__name__}: {e}'[:500],
      'trace_id': trace_id,
    }
    yield ResponsesAgentStreamEvent(type='response.error', error=error_payload)
    full_text = full_text or user_msg

  yield ResponsesAgentStreamEvent(type='response.output_text.done', item_id=msg_id)
  trace_id = _current_trace_id()
  custom: dict[str, Any] = {'citations': citations, 'trace_id': trace_id}
  if error_payload:
    custom['error'] = error_payload
  yield ResponsesAgentStreamEvent(
    type='response.output_item.done',
    item={
      'id': msg_id,
      'type': 'message',
      'role': 'assistant',
      'content': [{'type': 'output_text', 'text': full_text}],
    },
    custom_outputs=custom,
  )

  # Supervisor (LLM-as-judge) — stub, off by default. See server/supervisor.py
  # for the full design. Flipping KA_ENABLE_SUPERVISOR=true wires it in
  # without changing the agent's contract; the judge runs in the background.
  if not error_payload and os.getenv('KA_ENABLE_SUPERVISOR', '').lower() in ('1', 'true', 'yes'):
    import asyncio

    from server.supervisor import judge_response

    if trace_id and full_text and chunks:
      asyncio.create_task(judge_response(trace_id, query, full_text, chunks))
