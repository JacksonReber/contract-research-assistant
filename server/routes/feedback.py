"""User feedback → MLflow Assessments.

Writes thumbs + optional free-text comment as a feedback Assessment on the
trace. End-user identity comes from `X-Forwarded-Email` (Apps proxy header) —
or `local-dev` when running without the proxy.

Uses `mlflow.log_feedback()` rather than the REST API; MLflow's SDK picks up
ambient Databricks auth (the App SP in production, the local profile in dev).
This works even when the chat itself is OBO — Assessments are written by the
App SP, not the end user.
"""

from __future__ import annotations

import logging
from typing import Literal

import mlflow
from fastapi import APIRouter, HTTPException, Request
from mlflow.entities import AssessmentSource
from mlflow.entities.assessment_source import AssessmentSourceType
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/feedback')


def _user_email(request: Request) -> str:
  return (
    request.headers.get('x-forwarded-email')
    or request.headers.get('X-Forwarded-Email')
    or request.headers.get('x-forwarded-user')
    or request.headers.get('X-Forwarded-User')
    or 'local-dev'
  )


class FeedbackIn(BaseModel):
  trace_id: str = Field(min_length=1)
  vote: Literal['up', 'down']
  comment: str | None = None


class FeedbackOut(BaseModel):
  assessment_id: str | None = None
  trace_id: str
  vote: str
  has_comment: bool


@router.post('', response_model=FeedbackOut)
def submit_feedback(payload: FeedbackIn, request: Request):
  user = _user_email(request)
  try:
    assessment = mlflow.log_feedback(
      trace_id=payload.trace_id,
      name='user_feedback',
      value=payload.vote == 'up',
      source=AssessmentSource(
        source_type=AssessmentSourceType.HUMAN,
        source_id=user,
      ),
      rationale=(payload.comment or None),
    )
  except Exception as e:  # noqa: BLE001
    logger.exception('mlflow.log_feedback failed for trace_id=%s', payload.trace_id)
    raise HTTPException(502, f'feedback write failed: {e}') from e

  return FeedbackOut(
    assessment_id=getattr(assessment, 'assessment_id', None),
    trace_id=payload.trace_id,
    vote=payload.vote,
    has_comment=bool(payload.comment),
  )
