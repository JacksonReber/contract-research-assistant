import { CheckCircle2, MessageSquarePlus, ThumbsDown, ThumbsUp, X } from 'lucide-react';
import { useState } from 'react';
import { submitFeedback } from '@/lib/api';

interface FeedbackWidgetProps {
  traceId: string;
}

type Vote = 'up' | 'down' | null;

export function FeedbackWidget({ traceId }: FeedbackWidgetProps) {
  const [vote, setVote] = useState<Vote>(null);
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'done' | 'error'>(
    'idle'
  );
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function send(newVote: 'up' | 'down', includeComment: boolean) {
    setSubmitState('submitting');
    setErrorMsg(null);
    try {
      await submitFeedback({
        trace_id: traceId,
        vote: newVote,
        comment: includeComment && comment.trim() ? comment.trim() : undefined,
      });
      setVote(newVote);
      setSubmitState('done');
      if (includeComment) {
        setCommentOpen(false);
        setComment('');
      }
    } catch (e) {
      setErrorMsg((e as Error).message ?? String(e));
      setSubmitState('error');
    }
  }

  async function onThumbClick(newVote: 'up' | 'down') {
    if (submitState === 'submitting') return;
    // Toggle off if clicking the same vote (re-submit as opposite isn't supported by mlflow easily;
    // for now treat second click as no-op visual).
    if (vote === newVote) return;
    await send(newVote, false);
  }

  return (
    <div className="flex flex-col items-end gap-1" title={`trace_id ${traceId}`}>
      <div className="flex items-center gap-1">
        {submitState === 'done' && (
          <span className="flex items-center gap-1 text-[11px] text-green-700">
            <CheckCircle2 className="h-3 w-3" />
            thanks
          </span>
        )}
        {submitState === 'error' && (
          <span className="text-[11px] text-red-600" title={errorMsg ?? ''}>
            failed
          </span>
        )}
        <button
          type="button"
          onClick={() => onThumbClick('up')}
          disabled={submitState === 'submitting'}
          className={`rounded p-1 transition ${
            vote === 'up'
              ? 'bg-green-100 text-green-700'
              : 'text-slate-400 hover:bg-slate-100'
          } disabled:opacity-50`}
          title="Helpful"
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => onThumbClick('down')}
          disabled={submitState === 'submitting'}
          className={`rounded p-1 transition ${
            vote === 'down' ? 'bg-red-100 text-red-700' : 'text-slate-400 hover:bg-slate-100'
          } disabled:opacity-50`}
          title="Not helpful"
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => setCommentOpen((open) => !open)}
          className={`rounded p-1 transition ${
            commentOpen ? 'bg-blue-100 text-blue-700' : 'text-slate-400 hover:bg-slate-100'
          }`}
          title="Add a comment"
        >
          {commentOpen ? <X className="h-3.5 w-3.5" /> : <MessageSquarePlus className="h-3.5 w-3.5" />}
        </button>
      </div>
      {commentOpen && (
        <div className="flex w-72 flex-col gap-1 rounded-md border border-slate-200 bg-white p-2 shadow-sm">
          <textarea
            className="w-full resize-none rounded border border-slate-200 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
            rows={3}
            placeholder="What was good or bad about this answer?"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex items-center justify-between gap-2 text-[11px]">
            <span className="text-slate-400">
              {vote ? `vote: ${vote}` : 'Pick thumbs first or send comment-only'}
            </span>
            <div className="flex gap-1">
              <button
                type="button"
                disabled={!comment.trim() || submitState === 'submitting'}
                onClick={() => send(vote ?? 'up', true)}
                className="rounded bg-blue-600 px-2 py-1 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
