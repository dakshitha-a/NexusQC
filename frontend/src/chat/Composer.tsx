import { useState } from "react";
import { Send } from "lucide-react";

interface Props {
  disabled: boolean;
  disabledReason?: string;
  onSend: (text: string) => void;
}

export function Composer({ disabled, disabledReason, onSend }: Props) {
  const [text, setText] = useState("");

  const send = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className="shrink-0 border-t border-border p-3">
      {disabled && disabledReason && <div className="mb-1.5 text-xs text-text-muted">{disabledReason}</div>}
      <div className="flex items-end gap-2 rounded-lg border border-border bg-surface px-3 py-2 focus-within:border-accent">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          disabled={disabled}
          placeholder="e.g. 'water' or 'run a CASSCF(4,4)/cc-pVDZ on formaldehyde'"
          rows={1}
          className="max-h-40 min-h-6 flex-1 resize-none bg-transparent text-sm text-text placeholder:text-text-muted outline-none disabled:opacity-50"
        />
        <button
          onClick={send}
          disabled={disabled || !text.trim()}
          className="shrink-0 rounded-md bg-accent p-1.5 text-white disabled:opacity-30"
          title="Send"
        >
          <Send size={15} />
        </button>
      </div>
    </div>
  );
}
