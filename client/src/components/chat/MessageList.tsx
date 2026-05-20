import { useEffect, useRef } from 'react';
import type { ChatMessage } from '@/lib/types';
import { UserBubble } from './UserBubble';
import { AssistantBubble } from './AssistantBubble';

interface MessageListProps {
  messages: ChatMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center text-slate-400">
        <p className="text-sm">Ask a question about the contract corpus.</p>
        <p className="mt-1 text-xs">
          Try: <em>"What are the termination notice periods?"</em>
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 px-6 py-4">
      {messages.map((m) =>
        m.role === 'user' ? (
          <UserBubble key={m.id} text={m.text} />
        ) : (
          <AssistantBubble
            key={m.id}
            text={m.text}
            done={m.done}
            citations={m.citations}
            traceId={m.traceId}
            error={m.error}
          />
        )
      )}
      <div ref={bottomRef} />
    </div>
  );
}
