// --- Server-side config (from /api/config) ---

export interface AgentConfigPublic {
  agent: { name: string; description: string };
  vector_index: { name: string; endpoint: string };
  retrieval: { num_results: number; query_type: string };
  llm: { endpoint: string };
}

// --- Citations ---

export interface Citation {
  chunk_id: string;
  doc_id: string;
  source_type?: string;
  source_path?: string;
  page_num?: number;
  snippet: string;
  image_uri?: string;
  score?: number;
}

// --- Chat state ---

export interface UserMessage {
  id: string;
  role: 'user';
  text: string;
}

export interface MessageError {
  message: string;
  detail?: string;
  trace_id?: string | null;
}

export interface AssistantMessage {
  id: string;
  role: 'assistant';
  text: string;
  done: boolean;
  citations?: Citation[];
  traceId?: string;
  error?: MessageError;
}

export type ChatMessage = UserMessage | AssistantMessage;

// --- Threads (Lakebase chat history) ---

export interface ThreadSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface PersistedMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[] | null;
  trace_id: string | null;
  created_at: string;
}

export interface ThreadDetail extends ThreadSummary {
  messages: PersistedMessage[];
}

// --- Streaming events forwarded by AgentServer (ResponsesAgentStreamEvent envelope) ---

export type StreamEvent =
  | { type: 'response.created'; [k: string]: unknown }
  | {
      type: 'response.output_item.added';
      item: { id: string; type: string; role?: string };
      output_index: number;
      [k: string]: unknown;
    }
  | {
      type: 'response.output_item.done';
      item: {
        id: string;
        type: string;
        role?: string;
        content?: Array<{ type: string; text?: string }>;
      };
      custom_outputs?: { citations?: Citation[] };
      [k: string]: unknown;
    }
  | { type: 'response.output_text.delta'; item_id: string; delta: string; [k: string]: unknown }
  | { type: 'response.output_text.done'; item_id: string; [k: string]: unknown }
  | { type: 'response.completed'; [k: string]: unknown }
  | {
      type: 'response.error';
      error: { message: string; detail?: string; trace_id?: string | null };
      [k: string]: unknown;
    }
  | { type: string; [k: string]: unknown }; // forward-compat fallback
