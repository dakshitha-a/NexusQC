import { Loader2, Wrench } from "lucide-react";
import type { AgentStep } from "../lib/chatStore";

/** Live "what's happening right now" indicator for an in-progress turn --
 * replaces Streamlit's st.status(...) tool-call list with the same
 * information, rendered inline at the bottom of the message list instead
 * of a separate collapsible container. */
export function AgentStepChips({ steps, thinking }: { steps: AgentStep[]; thinking: boolean }) {
  if (!thinking && steps.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      {steps.length === 0 ? (
        <div className="flex items-center gap-1.5 text-xs text-text-muted">
          <Loader2 size={12} className="animate-spin" />
          Thinking...
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
