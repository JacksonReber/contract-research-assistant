import type { Citation } from '@/lib/types';
import { CitationCard } from './CitationCard';

interface CitationsListProps {
  citations?: Citation[];
  /** Question text that produced the shown answer (for the panel header). */
  heading?: string;
  /** True when viewing an earlier answer's sources rather than the latest. */
  pinned?: boolean;
  onOpen?: (c: Citation) => void;
}

export function CitationsList({ citations, heading, pinned, onOpen }: CitationsListProps) {
  if (!citations || citations.length === 0) {
    return (
      <div className="px-4 py-6 text-center text-xs text-slate-400">
        Citations for the selected answer will appear here. Click an answer's
        citation count to view its sources.
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col">
      {heading && (
        <div className="border-b border-slate-200 px-3 py-2">
          {pinned && (
            <div className="text-[10px] font-semibold uppercase tracking-wide text-blue-600">
              Pinned — earlier answer
            </div>
          )}
          <div className="truncate text-xs text-slate-500" title={heading}>
            Sources for: <span className="text-slate-700">{heading}</span>
          </div>
        </div>
      )}
      <div className="space-y-2 px-3 py-3">
        {citations.map((c, i) => (
          <CitationCard key={c.chunk_id ?? i} citation={c} rank={i + 1} onOpen={onOpen} />
        ))}
      </div>
    </div>
  );
}
