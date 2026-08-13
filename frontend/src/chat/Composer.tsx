import { useRef, useState } from "react";
import { Send } from "lucide-react";
import { useAttachedJobsStore } from "../lib/attachedJobsStore";

interface Props {
  disabled: boolean;
  disabledReason?: string;
  onSend: (text: string, jobIds: string[]) => void;
}

export function Composer({ disabled, disabledReason, onSend }: Props) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { attachedJobs, removeJob, clear } = useAttachedJobsStore();

  // Auto-grow: reset to "auto" first so scrollHeight reflects the
  // content's actual height (not the previously-set fixed height), then
  // set the height to match. max-h-40 in the className below still caps
  // it visually and lets it scroll past that.
  const resizeToContent = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  const send = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(
      trimmed,
      attachedJobs.map((j) => j.job_id),
    );
    setText("");
    clear();
    // Textarea content clears via the value prop, but height doesn't
    // auto-shrink without a re-measure -- reset it explicitly.
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  return (
    <div className="shrink-0 border-t border-border p-3">
      {attachedJobs.length > 0 && (
        <div className="mb-1.5 flex flex-wrap gap-1">
          {attachedJobs.map((j) => (
            <span
              key={j.job_id}
              className="flex items-center gap-1 rounded-full bg-accent-muted px-2 py-0.5 text-[11px] text-text"
            >
              {j.label}
              <button onClick={() => removeJob(j.job_id)} className="text-text-muted hover:text-text" title="Detach">
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
      {disabled && disabledReason && <div className="mb-1.5 text-xs text-text-muted">{disabledReason}</div>}
      <div className="flex items-end gap-2 rounded-lg border border-border bg-surface px-3 py-2 focus-within:border-accent">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            resizeToContent(e.target);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          disabled={disabled}
          placeholder="e.g. 'water' or 'run a CASSCF(4,4)/cc-pVDZ on formaldehyde'"
          rows={1}
          className="max-h-40 min-h-6 flex-1 resize-none overflow-y-auto bg-transparent text-sm text-text placeholder:text-text-muted outline-none disabled:opacity-50"
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
