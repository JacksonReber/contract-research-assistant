import { useCallback, useEffect, useRef, useState } from 'react';

import {
  appendMessage,
  createThread,
  deleteThread,
  fetchConfig,
  getThread,
  listThreads,
  streamChat,
} from '@/lib/api';
import type {
  AgentConfigPublic,
  AssistantMessage,
  ChatMessage,
  Citation,
  ThreadSummary,
  UserMessage,
} from '@/lib/types';

import { ChatLayout } from '@/components/layout/ChatLayout';
import { TopBar } from '@/components/layout/TopBar';
import { MessageList } from '@/components/chat/MessageList';
import { MessageInput } from '@/components/chat/MessageInput';
import { CitationsList } from '@/components/citations/CitationsList';
import { DocumentViewer } from '@/components/viewer/DocumentViewer';
import { ThreadList } from '@/components/threads/ThreadList';

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function summarizeTitle(text: string): string {
  const trimmed = text.trim().replace(/\s+/g, ' ');
  return trimmed.length > 60 ? trimmed.slice(0, 57) + '…' : trimmed;
}

export function ChatPage() {
  const [config, setConfig] = useState<AgentConfigPublic | undefined>();
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(true);
  const [historyEnabled, setHistoryEnabled] = useState(true);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load config + thread list on mount.
  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch((e) => setError(`Could not load /api/config: ${(e as Error).message}`));
  }, []);

  const refreshThreads = useCallback(async () => {
    setThreadsLoading(true);
    try {
      const list = await listThreads();
      setThreads(list);
      setHistoryEnabled(true);
    } catch (e) {
      const msg = (e as Error).message ?? String(e);
      if (msg.includes('503')) {
        setHistoryEnabled(false);
      } else {
        setError(`Could not list threads: ${msg}`);
      }
    } finally {
      setThreadsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshThreads();
  }, [refreshThreads]);

  const lastAssistant = [...messages]
    .reverse()
    .find((m): m is AssistantMessage => m.role === 'assistant');
  const lastCitations = lastAssistant?.citations;

  const updateAssistant = useCallback((id: string, patch: Partial<AssistantMessage>) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id && m.role === 'assistant' ? { ...m, ...patch } : m))
    );
  }, []);

  const onNewChat = useCallback(() => {
    abortRef.current?.abort();
    setCurrentThreadId(null);
    setMessages([]);
    setError(null);
  }, []);

  const onSelectThread = useCallback(
    async (id: string) => {
      if (streaming) return;
      setError(null);
      const detail = await getThread(id);
      if (!detail) {
        setError('Could not load thread (Lakebase unavailable).');
        return;
      }
      setCurrentThreadId(detail.id);
      setMessages(
        detail.messages.map<ChatMessage>((m) =>
          m.role === 'user'
            ? { id: m.id, role: 'user', text: m.content }
            : {
                id: m.id,
                role: 'assistant',
                text: m.content,
                done: true,
                citations: m.citations ?? [],
                traceId: m.trace_id ?? undefined,
              }
        )
      );
    },
    [streaming]
  );

  const onDeleteThread = useCallback(
    async (id: string) => {
      try {
        await deleteThread(id);
      } catch (e) {
        setError(`Could not delete thread: ${(e as Error).message}`);
        return;
      }
      if (currentThreadId === id) {
        setCurrentThreadId(null);
        setMessages([]);
      }
      refreshThreads();
    },
    [currentThreadId, refreshThreads]
  );

  const onSubmit = useCallback(
    async (text: string) => {
      if (streaming) return;
      setError(null);

      // Ensure we have a thread (create on first message of a new chat).
      let threadId = currentThreadId;
      if (historyEnabled && !threadId) {
        try {
          const created = await createThread(summarizeTitle(text));
          if (created) {
            threadId = created.id;
            setCurrentThreadId(threadId);
            setThreads((prev) => [created, ...prev]);
          }
        } catch (e) {
          // Persistence failure is non-fatal — keep chatting in-memory.
          console.warn('Could not create thread:', e);
        }
      }

      const userMsg: UserMessage = { id: uid(), role: 'user', text };
      const assistantId = uid();
      const assistantMsg: AssistantMessage = {
        id: assistantId,
        role: 'assistant',
        text: '',
        done: false,
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);

      // Persist user message (fire-and-forget so streaming isn't blocked).
      if (threadId) {
        appendMessage(threadId, { role: 'user', content: text }).catch((e) =>
          console.warn('persist user msg:', e)
        );
      }

      const history = [...messages, userMsg].map((m) => ({ role: m.role, content: m.text }));

      const ac = new AbortController();
      abortRef.current = ac;
      setStreaming(true);

      let accumulated = '';
      let finalCitations: Citation[] | undefined;
      let finalTraceId: string | undefined;
      let finalError: import('@/lib/types').MessageError | undefined;

      await streamChat({
        input: history,
        signal: ac.signal,
        onEvent: (ev) => {
          if (ev.type === 'response.output_text.delta' && typeof ev.delta === 'string') {
            accumulated += ev.delta;
            updateAssistant(assistantId, { text: accumulated });
          } else if (ev.type === 'response.error') {
            finalError = (ev as { error: import('@/lib/types').MessageError }).error;
          } else if (ev.type === 'response.output_item.done') {
            const customs = (
              ev as {
                custom_outputs?: {
                  citations?: Citation[];
                  trace_id?: string;
                  error?: import('@/lib/types').MessageError;
                };
              }
            ).custom_outputs;
            if (customs?.citations) finalCitations = customs.citations;
            if (customs?.trace_id) finalTraceId = customs.trace_id;
            if (customs?.error) finalError = customs.error;
            const item = (
              ev as { item?: { content?: Array<{ type: string; text?: string }> } }
            ).item;
            const fullText = item?.content?.find((c) => c.type === 'output_text')?.text;
            if (fullText && fullText.length > accumulated.length) {
              accumulated = fullText;
              updateAssistant(assistantId, { text: accumulated });
            }
          }
        },
        onDone: () => {
          updateAssistant(assistantId, {
            done: true,
            citations: finalCitations ?? [],
            traceId: finalTraceId,
            error: finalError,
          });
          setStreaming(false);
          abortRef.current = null;
          // Persist only successful responses — errored ones aren't useful in history.
          if (threadId && accumulated && !finalError) {
            appendMessage(threadId, {
              role: 'assistant',
              content: accumulated,
              citations: finalCitations,
              trace_id: finalTraceId,
            })
              .then(refreshThreads)
              .catch((e) => console.warn('persist assistant msg:', e));
          }
        },
        onError: (err) => {
          const message = (err as Error).message ?? String(err);
          updateAssistant(assistantId, {
            done: true,
            text: accumulated,
            citations: [],
            error: finalError ?? { message: 'Connection error', detail: message },
          });
          setStreaming(false);
          abortRef.current = null;
        },
      });
    },
    [currentThreadId, historyEnabled, messages, refreshThreads, streaming, updateAssistant]
  );

  const onCancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return (
    <>
      <ChatLayout
        topBar={<TopBar config={config} />}
        leftSidebar={
          <ThreadList
            threads={threads}
            currentThreadId={currentThreadId}
            onSelect={onSelectThread}
            onNew={onNewChat}
            onDelete={onDeleteThread}
            loading={threadsLoading}
            disabled={!historyEnabled}
          />
        }
        messages={
          <>
            {error && (
              <div className="border-b border-red-200 bg-red-50 px-6 py-2 text-xs text-red-700">
                {error}
              </div>
            )}
            <MessageList messages={messages} />
          </>
        }
        input={<MessageInput onSubmit={onSubmit} onCancel={onCancel} streaming={streaming} />}
        rightSidebar={<CitationsList citations={lastCitations} onOpen={setOpenCitation} />}
      />
      <DocumentViewer citation={openCitation} onClose={() => setOpenCitation(null)} />
    </>
  );
}
