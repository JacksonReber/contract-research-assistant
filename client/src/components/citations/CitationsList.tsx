import type { Citation } from '@/lib/types';
import { CitationCard } from './CitationCard';

interface CitationsListProps {
  citations?: Citation[];
  onOpen?: (c: Citation) => void;
}

export function CitationsList({ citations, onOpen }: CitationsListProps) {
  if (!citations || citations.length === 0) {
    return (
      <div className="px-4 py-6 text-center text-xs text-slate-400">
        Citations from the most recent answer will appear here.
      </div>
    );
  }
  return (
    <div className="space-y-2 px-3 py-3">
      {citations.map((c, i) => (
        <CitationCard key={c.chunk_id ?? i} citation={c} rank={i + 1} onOpen={onOpen} />
      ))}
    </div>
  );
}
