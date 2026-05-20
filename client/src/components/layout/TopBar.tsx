import type { AgentConfigPublic } from '@/lib/types';

interface TopBarProps {
  config?: AgentConfigPublic;
}

export function TopBar({ config }: TopBarProps) {
  return (
    <header className="border-b border-slate-200 bg-white px-6 py-3">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-slate-900">
            Contract Research Assistant
          </h1>
          <p className="text-xs text-slate-500">
            {config?.agent.description ?? 'RAG over the contract corpus'}
          </p>
        </div>
        {config && (
          <div className="text-right text-xs text-slate-500">
            <div>
              <span className="font-medium text-slate-700">LLM:</span> {config.llm.endpoint}
            </div>
            <div>
              <span className="font-medium text-slate-700">Index:</span>{' '}
              {config.vector_index.name.split('.').slice(-1)[0]}
              {' · '}
              {config.retrieval.query_type} · k={config.retrieval.num_results}
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
