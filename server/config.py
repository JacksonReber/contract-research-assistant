"""Load agent config from agent_config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class VectorIndexConfig:
  name: str
  endpoint: str
  columns: list[str]


@dataclass(frozen=True)
class RetrievalConfig:
  num_results: int
  query_type: str


@dataclass(frozen=True)
class LLMConfig:
  endpoint: str
  temperature: float
  max_tokens: int
  system_prompt: str


@dataclass(frozen=True)
class AgentConfig:
  name: str
  description: str
  vector_index: VectorIndexConfig
  retrieval: RetrievalConfig
  llm: LLMConfig

  def public_view(self) -> dict:
    return {
      'agent': {'name': self.name, 'description': self.description},
      'vector_index': {
        'name': self.vector_index.name,
        'endpoint': self.vector_index.endpoint,
      },
      'retrieval': {
        'num_results': self.retrieval.num_results,
        'query_type': self.retrieval.query_type,
      },
      'llm': {'endpoint': self.llm.endpoint},
    }


def load_agent_config(path: str | None = None) -> AgentConfig:
  cfg_path = Path(path or os.getenv('AGENT_CONFIG_PATH', 'agent_config.yaml'))
  if not cfg_path.is_absolute():
    cfg_path = Path(__file__).parent.parent / cfg_path
  with cfg_path.open() as f:
    raw = yaml.safe_load(f)['agent']

  return AgentConfig(
    name=raw['name'],
    description=raw['description'],
    vector_index=VectorIndexConfig(
      name=raw['vector_index']['name'],
      endpoint=raw['vector_index']['endpoint'],
      columns=list(raw['vector_index']['columns']),
    ),
    retrieval=RetrievalConfig(
      num_results=int(raw['retrieval']['num_results']),
      query_type=raw['retrieval']['query_type'],
    ),
    llm=LLMConfig(
      endpoint=raw['llm']['endpoint'],
      temperature=float(raw['llm'].get('temperature', 0.0)),
      max_tokens=int(raw['llm'].get('max_tokens', 2048)),
      system_prompt=raw['llm']['system_prompt'].strip(),
    ),
  )
