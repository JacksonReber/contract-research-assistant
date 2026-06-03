import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AlertCircle, Bot } from 'lucide-react';
import { useState } from 'react';
import type { Citation, MessageError } from '@/lib/types';
import { FeedbackWidget } from '@/components/feedback/FeedbackWidget';

interface AssistantBubbleProps {
  messageId: string;
  text: string;
  done: boolean;
  citations?: Citation[];
  traceId?: string;
  error?: MessageError;
  /** Whether this answer's citations are the ones currently shown in the sidebar. */
  selected?: boolean;
  /** Pin this answer's citations into the sidebar. */
  onSelectCitations?: (id: string) => void;
}

export function AssistantBubble({
  messageId,
  text,
  done,
  citations,
  traceId,
  error,
  selected,
  onSelectCitations,
}: AssistantBubbleProps) {
  const showThinking = !done && text.length === 0;
  return (
    <div className="flex items-start gap-3">
      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200">
        <Bot className="h-4 w-4 text-slate-600" />
      </div>
      <div className="max-w-[80%] flex-1 space-y-2">
        {error ? (
          <ErrorCard err={error} />
        ) : (
          <div className="rounded-2xl rounded-tl-md bg-white px-4 py-3 text-sm text-slate-900 shadow-sm ring-1 ring-slate-200">
            {showThinking ? (
              <div className="flex items-center gap-2 text-slate-500">
                <ThinkingDots />
                <span>retrieving + drafting…</span>
              </div>
            ) : (
              <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
                {!done && (
                  <span className="ml-1 inline-block h-3 w-2 animate-pulse bg-slate-300" />
                )}
              </div>
            )}
          </div>
        )}
        {done && !error && citations !== undefined && (
          <div className="flex items-center justify-between text-xs text-slate-500">
            {citations.length > 0 ? (
              <button
                type="button"
                onClick={() => onSelectCitations?.(messageId)}
                aria-pressed={selected}
                title="Show these sources in the sidebar"
                className={
                  'rounded-full px-2 py-0.5 font-medium transition-colors ' +
                  (selected
                    ? 'bg-blue-100 text-blue-700 ring-1 ring-blue-300'
                    : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700')
                }
              >
                {citations.length} {citations.length === 1 ? 'citation' : 'citations'}
              </button>
            ) : (
              <span>no citations</span>
            )}
            {traceId && <FeedbackWidget traceId={traceId} />}
          </div>
        )}
      </div>
    </div>
  );
}

function ErrorCard({ err }: { err: MessageError }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl rounded-tl-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
      <div className="flex items-start gap-2">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
        <div className="flex-1">
          <div className="font-medium">{err.message}</div>
          {err.detail && (
            <button
              type="button"
              className="mt-1 text-xs text-red-700 underline hover:text-red-900"
              onClick={() => setOpen((o) => !o)}
            >
              {open ? 'Hide details' : 'Show details'}
            </button>
          )}
          {open && err.detail && (
            <pre className="mt-2 whitespace-pre-wrap break-words rounded bg-red-100 p-2 text-[11px] text-red-900">
              {err.detail}
            </pre>
          )}
          {err.trace_id && (
            <div className="mt-1 break-all font-mono text-[10px] text-red-700">
              trace_id: {err.trace_id}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <span className="inline-flex gap-1">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
    </span>
  );
}
