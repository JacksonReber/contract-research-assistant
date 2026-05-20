import { useState } from 'react';
import { Send, Square } from 'lucide-react';

interface MessageInputProps {
  onSubmit: (text: string) => void;
  onCancel?: () => void;
  streaming: boolean;
}

export function MessageInput({ onSubmit, onCancel, streaming }: MessageInputProps) {
  const [value, setValue] = useState('');

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || streaming) return;
    onSubmit(trimmed);
    setValue('');
  }

  return (
    <div className="border-t border-slate-200 bg-white px-6 py-3">
      <div className="flex items-end gap-2">
        <textarea
          className="flex-1 resize-none rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-slate-50"
          rows={2}
          placeholder="Ask about the contracts…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        {streaming ? (
          <button
            className="flex h-10 items-center gap-1 rounded-md bg-slate-200 px-3 text-sm font-medium text-slate-700 hover:bg-slate-300"
            onClick={onCancel}
            title="Cancel streaming"
          >
            <Square className="h-4 w-4 fill-current" />
            Stop
          </button>
        ) : (
          <button
            className="flex h-10 items-center gap-1 rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            onClick={submit}
            disabled={!value.trim()}
          >
            <Send className="h-4 w-4" />
            Send
          </button>
        )}
      </div>
      <p className="mt-1 text-xs text-slate-400">Enter to send · Shift+Enter for newline</p>
    </div>
  );
}
