import { ExternalLink, FileText } from 'lucide-react';
import type { Citation } from '@/lib/types';

interface CitationCardProps {
  citation: Citation;
  rank: number;
  onOpen?: (c: Citation) => void;
}

export function CitationCard({ citation, rank, onOpen }: CitationCardProps) {
  const docLabel = citation.doc_id || 'unknown';
  const pageLabel = citation.page_num != null ? `p. ${citation.page_num}` : null;
  return (
    <button
      type="button"
      onClick={() => onOpen?.(citation)}
      className="group block w-full rounded-md border border-slate-200 bg-white p-3 text-left text-xs shadow-sm transition hover:border-blue-300 hover:bg-blue-50"
    >
      <div className="flex items-start gap-2">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-semibold text-slate-600 group-hover:bg-blue-100 group-hover:text-blue-700">
          {rank}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1 truncate font-medium text-slate-700">
            <FileText className="h-3 w-3 shrink-0" />
            <span className="truncate" title={docLabel}>
              {docLabel}
            </span>
          </div>
          <div className="mt-0.5 flex gap-2 text-[10px] text-slate-500">
            {pageLabel && <span>{pageLabel}</span>}
            {typeof citation.score === 'number' && (
              <span>score={citation.score.toFixed(2)}</span>
            )}
            {citation.source_type && (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 uppercase">
                {citation.source_type}
              </span>
            )}
          </div>
          <p className="mt-1.5 line-clamp-3 text-[11px] leading-snug text-slate-600">
            {citation.snippet}
          </p>
          <div className="mt-1.5 flex items-center gap-1 text-[10px] text-slate-400 opacity-0 transition group-hover:opacity-100">
            <ExternalLink className="h-3 w-3" />
            <span>Open in viewer</span>
          </div>
        </div>
      </div>
    </button>
  );
}
