import type {
  AgentConfigPublic,
  Citation,
  PersistedMessage,
  StreamEvent,
  ThreadDetail,
  ThreadSummary,
} from './types';

export async function fetchConfig(): Promise<AgentConfigPublic> {
  const r = await fetch('/api/config');
  if (!r.ok) throw new Error(`config: ${r.status}`);
  return r.json();
}

// --- Threads (Lakebase) ---

function isNotConfiguredError(status: number): boolean {
  return status === 503;
}

export async function listThreads(): Promise<ThreadSummary[]> {
  const r = await fetch('/api/threads');
  if (isNotConfiguredError(r.status)) return [];
  if (!r.ok) throw new Error(`listThreads: ${r.status}`);
  return r.json();
}

export async function createThread(title?: string): Promise<ThreadSummary | null> {
  const r = await fetch('/api/threads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (isNotConfiguredError(r.status)) return null;
  if (!r.ok) throw new Error(`createThread: ${r.status}`);
  return r.json();
}

export async function getThread(id: string): Promise<ThreadDetail | null> {
  const r = await fetch(`/api/threads/${id}`);
  if (isNotConfiguredError(r.status)) return null;
  if (!r.ok) throw new Error(`getThread: ${r.status}`);
  return r.json();
}

export async function appendMessage(
  threadId: string,
  payload: {
    role: 'user' | 'assistant';
    content: string;
    citations?: Citation[];
    trace_id?: string;
  }
): Promise<PersistedMessage | null> {
  const r = await fetch(`/api/threads/${threadId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (isNotConfiguredError(r.status)) return null;
  if (!r.ok) throw new Error(`appendMessage: ${r.status}`);
  return r.json();
}

export async function renameThread(id: string, title: string): Promise<ThreadSummary | null> {
  const r = await fetch(`/api/threads/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (isNotConfiguredError(r.status)) return null;
  if (!r.ok) throw new Error(`renameThread: ${r.status}`);
  return r.json();
}

export async function deleteThread(id: string): Promise<boolean> {
  const r = await fetch(`/api/threads/${id}`, { method: 'DELETE' });
  if (isNotConfiguredError(r.status)) return false;
  if (!r.ok) throw new Error(`deleteThread: ${r.status}`);
  return true;
}

// --- Feedback (MLflow Assessments) ---

export async function submitFeedback(payload: {
  trace_id: string;
  vote: 'up' | 'down';
  comment?: string;
}): Promise<{ assessment_id: string | null; has_comment: boolean }> {
  const r = await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`submitFeedback ${r.status}: ${text.slice(0, 200)}`);
  }
  return r.json();
}

export interface StreamChatOptions {
  // ResponsesAgent input — array of {role, content} messages
  input: Array<{ role: string; content: string }>;
  customInputs?: Record<string, unknown>;
  signal?: AbortSignal;
  onEvent: (ev: StreamEvent) => void;
  onDone: () => void;
  onError: (err: unknown) => void;
}

export async function streamChat({
  input,
  customInputs,
  signal,
  onEvent,
  onDone,
  onError,
}: StreamChatOptions) {
  try {
    const body: Record<string, unknown> = { input, stream: true };
    if (customInputs && Object.keys(customInputs).length > 0) {
      body.custom_inputs = customInputs;
    }
    const resp = await fetch('/invocations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(body),
      signal,
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`/invocations ${resp.status}: ${text.slice(0, 400)}`);
    }
    if (!resp.body) throw new Error('no response body');

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        for (const line of block.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6).trim();
          if (payload === '[DONE]') {
            onDone();
            return;
          }
          try {
            const obj = JSON.parse(payload) as StreamEvent;
            onEvent(obj);
          } catch (e) {
            console.warn('failed to parse event', payload, e);
          }
        }
      }
    }
    onDone();
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError') {
      onDone();
      return;
    }
    onError(e);
  }
}
