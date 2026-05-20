"""Supervisor (LLM-as-judge) scaffold — STUB, not wired into the live agent.

Pattern intent
--------------
Supervisor agents are framed as "more reliable than user feedback" — i.e.
an automated groundedness/quality judge that scores every response without
waiting for end-user thumbs.

This module shows the SHAPE to target when wiring one in:
- After the main agent produces an answer, an asynchronous judge call
  scores the answer for groundedness against the retrieved chunks.
- The score is written back as an MLflow `Assessment` with
  `source_type=LLM_JUDGE`, so it shows up next to human feedback in the
  Experiments UI and is queryable from the OTel annotations table.

Activation
----------
Not wired into `server/agent.py`'s `@invoke` / `@stream` handlers. The
intended wire-in is documented inline in `agent.py`. Flipping the
`KA_ENABLE_SUPERVISOR` env var to `true` (and uncommenting the wire-in
block) would activate it without changing the agent's public contract —
the judge runs in the background after streaming completes.

Why stub, not active
--------------------
- Extra latency on the chat call (1-3s for a second LLM round-trip).
- Doubles the LLM cost per request.
- Judge prompt + scoring rubric haven't been validated against any
  ground-truth eval yet — shipping it active without calibration would
  mean writing noisy scores to MLflow.
- Better to add it once a small eval set exists to tune the judge prompt
  against.
"""

from __future__ import annotations

import json
import logging

import mlflow
from databricks_openai import AsyncDatabricksOpenAI
from mlflow.entities import AssessmentSource
from mlflow.entities.assessment_source import AssessmentSourceType

logger = logging.getLogger(__name__)


JUDGE_SYSTEM_PROMPT = """You are a strict reviewer of contract-research answers.

For each answer you receive, judge how well it is grounded in the retrieved
contract excerpts. Return ONLY a JSON object with two keys:

  "groundedness": float between 0.0 and 1.0
    1.0 = every claim is directly supported by the excerpts
    0.5 = mix of supported and unsupported claims
    0.0 = answer fabricates content not present in the excerpts
  "rationale": one short sentence explaining the score

Do not include any other text outside the JSON.
"""


async def judge_response(
  trace_id: str,
  query: str,
  answer: str,
  chunks: list[dict],
  judge_endpoint: str = 'databricks-claude-sonnet-4-5',
) -> dict:
  """Run the supervisor judge against a single agent response.

  Writes the resulting `groundedness` score as an MLflow Assessment on the
  trace, with `source_type=LLM_JUDGE` and the judge endpoint as the source_id.

  Returns the parsed judge JSON (`{groundedness, rationale}`).
  """
  context = '\n\n---\n\n'.join(
    f'[doc_id={c.get("doc_id", "?")} chunk_id={c.get("chunk_id", "?")}]\n'
    f'{c.get("chunk_to_retrieve", c.get("snippet", ""))}'
    for c in chunks
  )
  user_msg = (
    f'Question:\n{query}\n\n'
    f'Answer to evaluate:\n{answer}\n\n'
    f'Retrieved excerpts available to the agent:\n{context}'
  )
  client = AsyncDatabricksOpenAI()  # SP-scoped — judge isn't user-attributed
  resp = await client.chat.completions.create(
    model=judge_endpoint,
    messages=[
      {'role': 'system', 'content': JUDGE_SYSTEM_PROMPT},
      {'role': 'user', 'content': user_msg},
    ],
    temperature=0.0,
    max_tokens=200,
  )
  raw = (resp.choices[0].message.content or '').strip()
  try:
    parsed = json.loads(raw)
    score = float(parsed.get('groundedness', 0.0))
    rationale = parsed.get('rationale') or ''
  except (json.JSONDecodeError, ValueError, TypeError):
    logger.warning('judge returned unparseable response: %r', raw[:200])
    return {'groundedness': None, 'rationale': raw[:200], 'raw': raw}

  try:
    mlflow.log_feedback(
      trace_id=trace_id,
      name='groundedness',
      value=score,
      source=AssessmentSource(
        source_type=AssessmentSourceType.LLM_JUDGE,
        source_id=judge_endpoint,
      ),
      rationale=rationale,
    )
  except Exception:  # noqa: BLE001
    logger.exception('mlflow.log_feedback failed for judge score on %s', trace_id)

  return {'groundedness': score, 'rationale': rationale}


# Wire-in design (pseudocode for future activation in server/agent.py):
#
#   import asyncio, os
#   from server.supervisor import judge_response
#
#   if os.getenv('KA_ENABLE_SUPERVISOR', '').lower() in ('1', 'true', 'yes'):
#       # Inside @stream after the final ResponsesAgentStreamEvent:
#       trace_id = _current_trace_id()
#       if trace_id and full_text and chunks:
#           # Fire-and-forget so streaming response isn't delayed.
#           asyncio.create_task(
#               judge_response(trace_id, query, full_text, chunks)
#           )
