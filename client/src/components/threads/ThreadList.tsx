import { useState } from 'react';
import { MessageSquare, Plus, Trash2 } from 'lucide-react';
import type { ThreadSummary } from '@/lib/types';

interface ThreadListProps {
  threads: ThreadSummary[];
  currentThreadId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  loading?: boolean;
  disabled?: boolean;
}

export function ThreadList({
  threads,
  currentThreadId,
  onSelect,
  onNew,
  onDelete,
  loading,
  disabled,
}: ThreadListProps) {
  if (disabled) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-3 text-center text-xs text-slate-400">
        <MessageSquare className="mb-2 h-5 w-5" />
        <p>Chat history disabled (Lakebase not configured).</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 px-3 py-2">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
        >
          <Plus className="h-3.5 w-3.5" />
          New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="px-3 py-3 text-center text-xs text-slate-400">Loading…</div>
        )}
        {!loading && threads.length === 0 && (
          <div className="px-3 py-3 text-center text-xs text-slate-400">No conversations yet.</div>
        )}
        {threads.map((t) => (
          <ThreadRow
            key={t.id}
            thread={t}
            selected={t.id === currentThreadId}
            onSelect={() => onSelect(t.id)}
            onDelete={() => onDelete(t.id)}
          />
        ))}
      </div>
    </div>
  );
}

function ThreadRow({
  thread,
  selected,
  onSelect,
  onDelete,
}: {
  thread: ThreadSummary;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      className={`group relative flex items-center gap-2 px-3 py-2 text-xs ${
        selected ? 'bg-blue-50' : 'hover:bg-slate-100'
      }`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        onClick={onSelect}
        className={`flex min-w-0 flex-1 items-center gap-2 truncate text-left ${
          selected ? 'text-blue-700' : 'text-slate-700'
        }`}
        title={thread.title}
      >
        <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />
        <span className="truncate">{thread.title}</span>
      </button>
      {hovered && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            if (window.confirm(`Delete "${thread.title}"?`)) onDelete();
          }}
          className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-red-600"
          title="Delete"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
