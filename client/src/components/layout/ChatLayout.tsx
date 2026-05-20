import type { ReactNode } from 'react';

interface ChatLayoutProps {
  topBar: ReactNode;
  leftSidebar: ReactNode;
  messages: ReactNode;
  input: ReactNode;
  rightSidebar: ReactNode;
}

export function ChatLayout({
  topBar,
  leftSidebar,
  messages,
  input,
  rightSidebar,
}: ChatLayoutProps) {
  return (
    <div className="flex h-screen flex-col">
      {topBar}
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-slate-50 md:flex">
          <div className="border-b border-slate-200 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
            Conversations
          </div>
          <div className="min-h-0 flex-1">{leftSidebar}</div>
        </aside>
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50">{messages}</div>
          {input}
        </main>
        <aside className="hidden w-80 shrink-0 flex-col border-l border-slate-200 bg-slate-50 md:flex">
          <div className="border-b border-slate-200 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
            Citations
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{rightSidebar}</div>
        </aside>
      </div>
    </div>
  );
}
