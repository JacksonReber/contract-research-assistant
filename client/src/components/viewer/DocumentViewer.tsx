import { Download, ExternalLink, FileText, X } from 'lucide-react';
import { useMemo } from 'react';
import type { Citation } from '@/lib/types';

interface DocumentViewerProps {
  citation: Citation | null;
  onClose: () => void;
}

function buildPdfUrl(citation: Citation): string | null {
  const path = citation.source_path;
  if (!path || !path.toLowerCase().endsWith('.pdf')) return null;
  const base = `/api/documents?path=${encodeURIComponent(path)}`;
  // Browser PDF viewers honor `#page=N` to scroll-to-page.
  return citation.page_num ? `${base}#page=${citation.page_num}` : base;
}

export function DocumentViewer({ citation, onClose }: DocumentViewerProps) {
  const pdfUrl = useMemo(() => (citation ? buildPdfUrl(citation) : null), [citation]);
  if (!citation) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-[560px] flex-col border-l border-slate-200 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <FileText className="h-4 w-4 shrink-0 text-slate-500" />
          <span
            className="truncate text-sm font-medium text-slate-700"
            title={citation.doc_id}
          >
            {citation.doc_id}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {pdfUrl && (
            <>
              <a
                href={pdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                title="Open in new tab"
              >
                <ExternalLink className="h-4 w-4" />
              </a>
              <a
                href={`/api/documents?path=${encodeURIComponent(citation.source_path || '')}`}
                download
                className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                title="Download"
              >
                <Download className="h-4 w-4" />
              </a>
            </>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        {pdfUrl ? (
          <iframe
            key={pdfUrl}
            src={pdfUrl}
            title={citation.doc_id || 'document'}
            className="min-h-0 flex-1 border-0 bg-slate-50"
          />
        ) : (
          <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-slate-500">
            No PDF available for this citation.
          </div>
        )}

        <div className="border-t border-slate-200 bg-white px-4 py-3 text-xs">
          <div className="grid grid-cols-2 gap-2 text-slate-600">
            <Field label="page_num" value={citation.page_num ?? '—'} />
            <Field label="score" value={citation.score?.toFixed(3) ?? '—'} />
            <Field
              label="source_type"
              value={citation.source_type ?? '—'}
            />
            <Field label="chunk_id" value={shortChunkId(citation.chunk_id ?? '')} mono />
          </div>
          {citation.snippet && (
            <details className="mt-3">
              <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700">
                Retrieved snippet
              </summary>
              <div className="mt-1 rounded-md bg-slate-50 p-2 text-[11px] leading-relaxed text-slate-700">
                {citation.snippet}
              </div>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className={`break-words ${mono ? 'font-mono text-[10px]' : ''}`}>{value}</div>
    </div>
  );
}

function shortChunkId(id: string): string {
  if (id.length <= 40) return id;
  return `${id.slice(0, 28)}…${id.slice(-8)}`;
}
