import { useEffect, useRef, useState } from "react";
import { ArrowDown, AlertCircle } from "lucide-react";
import { useChatStore } from "../lib/chatStore";
import { useActiveThreadController } from "../lib/useActiveThreadController";
import * as api from "../lib/api";
import { MessageBubbleRow, AssistantBubble } from "./MessageBubble";
import { AgentStepChips } from "./AgentStepChips";
import { Composer } from "./Composer";
import { JobApprovalCard } from "../approvals/JobApprovalCard";
import { ToolApprovalCard } from "../approvals/ToolApprovalCard";

export function ChatPane() {
  const { activeThreadId } = useActiveThreadController();
  const {
    messages,
    streaming,
    activeSteps,
    turnInProgress,
    pendingApproval,
    error,
    clearError,
    optimisticUserMessage,
    sseConnected,
    lastTurnStopped,
  } = useChatStore();

  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoStick, setAutoStick] = useState(true);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAutoStick(distanceFromBottom < 80);
  };

  useEffect(() => {
    if (autoStick && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, streaming, activeSteps, pendingApproval]);

  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setAutoStick(true);
  };

  const handleSend = (text: string, jobIds: string[]) => {
    if (!activeThreadId) return;
    optimisticUserMessage(text);
    api.postMessage(activeThreadId, text, jobIds).catch((e) => {
      useChatStore.getState().applyEvent({ type: "error", message: String(e) });
    });
  };

  // Independent of `disabled` below on purpose -- Stop must stay clickable
  // for exactly the state (turnInProgress) that makes the composer's
  // textarea/Send disabled, so the user can interrupt a stuck turn instead
  // of being locked out until it finishes on its own.
  const handleStop = () => {
    if (!activeThreadId) return;
    api.stopTurn(activeThreadId).catch((e) => {
      useChatStore.getState().applyEvent({ type: "error", message: String(e) });
    });
  };

  const disabled = !activeThreadId || !sseConnected || turnInProgress || !!pendingApproval;
  const disabledReason = pendingApproval
    ? "Resolve the pending approval above before sending another message."
    : !sseConnected && activeThreadId
      ? "Connecting..."
      : undefined;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4"
        >
          {messages.length === 0 && !turnInProgress && (
            <div className="flex flex-1 items-center justify-center text-sm text-text-muted">
              Name a molecule (or give a SMILES) to visualize it, or ask for a calculation directly.
            </div>
          )}
          {messages.map((m, i) => (
            <MessageBubbleRow key={m.id ?? `pending-${i}`} message={m} />
          ))}
          {Object.entries(streaming).map(([id, text]) => (
            <AssistantBubble key={id} content={text} />
          ))}
          {error && (
            <div className="rounded-lg border border-status-failed/40 bg-status-failed/10 px-3.5 py-2 text-sm text-status-failed">
              {error}
              <button onClick={clearError} className="ml-2 underline">
                dismiss
              </button>
            </div>
          )}
          <AgentStepChips steps={activeSteps} thinking={turnInProgress && Object.keys(streaming).length === 0} />
          {!turnInProgress && lastTurnStopped && (
            <div className="text-xs text-text-muted">Stopped -- send a new message when ready.</div>
          )}
          {pendingApproval && activeThreadId && (
            pendingApproval.kind === "job_approval" ? (
              <JobApprovalCard pending={pendingApproval} threadId={activeThreadId} />
            ) : (
              <ToolApprovalCard pending={pendingApproval} threadId={activeThreadId} />
            )
          )}
        </div>

        {!autoStick && (
          <button
            onClick={jumpToLatest}
            className={`absolute left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs shadow-lg ${
              pendingApproval
                ? "bottom-3 border-status-running/50 bg-status-running/15 text-status-running"
                : "bottom-3 border-border bg-surface-raised text-text"
            }`}
          >
            {pendingApproval ? <AlertCircle size={12} /> : <ArrowDown size={12} />}
            {pendingApproval ? "Action needed -- jump to approval" : "Jump to latest"}
          </button>
        )}
      </div>

      <Composer
        disabled={disabled}
        disabledReason={disabledReason}
        onSend={handleSend}
        turnInProgress={turnInProgress}
        onStop={handleStop}
      />
    </div>
  );
}
