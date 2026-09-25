import { useEffect, useState } from "react";
import { Loader2, Wrench } from "lucide-react";
import type { AgentStep } from "../lib/chatStore";

/** Whole seconds since `active` last became true, ticking once a second;
 * 0 while inactive. Restarts each time it turns on, so the count after a
 * tool finishes is the model's time on the reply, not the whole turn's. */
function useElapsedSeconds(active: boolean): number {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) {
      setStartedAt(null);
      return;
    }
    const start = Date.now();
    setStartedAt(start);
    setNow(start);
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000));
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

/** Live "what's happening right now" indicator for an in-progress turn --
 * replaces Streamlit's st.status(...) tool-call list with the same
 * information, rendered inline at the bottom of the message list instead
 * of a separate collapsible container.
 *
 * "Thinking..." carries a running count of seconds. A model call can take a
 * minute or more before its first token, and a spinner that shows no change
 * for that long reads as a chat that has died; on 2026-09-24 a user sat
 * through 106 s of one and then typed "hello?". The count is shown from the
 * third second, so an ordinary quick reply does not flash a number. */
export function AgentStepChips({ steps, thinking }: { steps: AgentStep[]; thinking: boolean }) {
  const waiting = thinking && steps.length === 0;
  const elapsed = useElapsedSeconds(waiting);
  if (!thinking && steps.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      {steps.length === 0 ? (
        <div className="flex items-center gap-1.5 text-xs text-text-muted" data-testid="agent-thinking">
          <Loader2 size={12} className="animate-spin" />
          Thinking...
          {elapsed >= 3 && (
            <span className="tabular-nums" data-testid="agent-thinking-elapsed">
              {formatElapsed(elapsed)}
            </span>
          )}
        </div>
      ) : (
        steps.map((step, i) => (
          <div key={`${step.toolName}-${i}`} className="flex items-center gap-1.5 text-xs text-text-muted">
            <Wrench size={12} className="animate-pulse" />
            <span className="font-mono">{step.toolName}</span>
            <span>running...</span>
          </div>
        ))
      )}
    </div>
  );
}
