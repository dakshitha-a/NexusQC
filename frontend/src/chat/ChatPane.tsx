import { useEffect, useRef, useState } from "react";
import { ArrowDown, AlertCircle, Loader2 } from "lucide-react";
import { useChatStore } from "../lib/chatStore";
import { useActiveThreadController } from "../lib/useActiveThreadController";
import * as api from "../lib/api";
import { MessageBubbleRow, AssistantBubble } from "./MessageBubble";
import { WelcomeMessage } from "./WelcomeMessage";
import { AgentStepChips } from "./AgentStepChips";
import { Composer } from "./Composer";
import { JobApprovalCard } from "../approvals/JobApprovalCard";

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
    sseHasConnectedOnce,
    lastTurnStopped,
    threadLoading,
    threadLoadError,
  } = useChatStore();

  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoStick, setAutoStick] = useState(true);
  // True from the moment Stop is clicked until turnInProgress actually
  // clears -- drives the Stop button's own disabled/"Stopping..." state
  // (a raw un-debounced button let repeated clicks look like nothing was
  // happening, since the backend can take a few seconds to unwind a
  // turn that's mid-tool-call -- see stop_turn's docstring in
  // server/routes/chat.py) and the safety-net timeout below.
  const [stopRequested, setStopRequested] = useState(false);

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

  // turnInProgress clearing (normal turn_complete/error SSE event) is the
  // expected way stopRequested resolves -- clear it whenever that happens
  // so the button goes back to normal, and also on a thread switch so a
  // stale "Stopping..." from one conversation can't bleed into another.
  useEffect(() => {
    if (!turnInProgress) setStopRequested(false);
  }, [turnInProgress]);
  useEffect(() => {
    setStopRequested(false);
  }, [activeThreadId]);

  // Safety net for exactly the case stop_turn's own docstring (server/
  // routes/chat.py) admits it can't fully solve: a turn blocked inside a
  // long-running synchronous tool call (or, in the worst case, a backend
  // that died mid-turn without ever getting to publish turn_complete/
  // error) never un-sticks the composer on its own. Without this, the
  // only recovery from that state was a full page reload. 45s is well
  // past the ~10s worst case measured for a real tool-call-then-generate
  // round trip during this fix's own verification, while still being
  // short enough that a genuinely stuck turn doesn't lock the user out
  // for long.
  useEffect(() => {
    if (!stopRequested) return;
    const timer = window.setTimeout(() => {
      useChatStore.setState((s) =>
        s.turnInProgress
          ? {
              turnInProgress: false,
              activeSteps: [],
              streaming: {},
              lastTurnStopped: true,
              error:
                "Stop is taking longer than expected -- the backend may still be finishing a step in the " +
                "background. You can send a new message now; it will run once that step actually completes.",
            }
          : {},
      );
    }, 45000);
    return () => window.clearTimeout(timer);
  }, [stopRequested]);

  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setAutoStick(true);
  };

  const handleSend = (text: string, jobIds: string[], frameId: string | null) => {
    if (!activeThreadId) return;
    optimisticUserMessage(text);
    api.postMessage(activeThreadId, text, jobIds, frameId).catch((e) => {
      useChatStore.getState().applyEvent({ type: "error", message: String(e) });
    });
  };

  // Independent of `disabled` below on purpose -- Stop must stay clickable
  // for exactly the state (turnInProgress) that makes the composer's
  // textarea/Send disabled, so the user can interrupt a stuck turn instead
  // of being locked out until it finishes on its own.
  const handleStop = () => {
    if (!activeThreadId || stopRequested) return;
    setStopRequested(true);
    api.stopTurn(activeThreadId).catch((e) => {
      setStopRequested(false);
      useChatStore.getState().applyEvent({ type: "error", message: String(e) });
    });
  };

  const disabled = !activeThreadId || !sseConnected || turnInProgress || !!pendingApproval;
  // Distinguish "connecting for the first time" from "the connection that
  // was already up just dropped" -- these previously looked identical
  // (both just showed "Connecting...") even though the second is a real
  // network/backend problem worth calling out, not routine startup.
  const disabledReason = pendingApproval
    ? "Resolve the pending approval above before sending another message."
    : !sseConnected && activeThreadId
      ? sseHasConnectedOnce
        ? "Lost connection to the server -- reconnecting..."
        : "Connecting..."
      : undefined;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4"
        >
          {/* An existing conversation whose state is still loading must not
              render the "start a new conversation" welcome screen -- that
              wait is genuinely long when the thread's own agent turn holds
              its lock (19.5s measured for an ordinary turn; longer for
              job_watcher's retry turn), and a user returning to a
              conversation whose job just failed would read an empty
              conversation as lost work. See threadLoading in chatStore. */}
          {threadLoading && (
            <div
              data-testid="chat-thread-loading"
              className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-text-muted"
            >
              <Loader2 size={18} className="animate-spin" />
              <div>Loading this conversation…</div>
              <div className="max-w-xs text-center text-[11px]">
                If a calculation just finished, the agent may still be writing up the
                results — this waits for that to complete.
              </div>
            </div>
          )}
          {threadLoadError && !threadLoading && (
            <div
              data-testid="chat-thread-load-error"
              className="rounded-lg border border-status-failed/40 bg-status-failed/10 px-3.5 py-2 text-sm text-status-failed"
            >
              Could not load this conversation: {threadLoadError}
            </div>
          )}
          {messages.length === 0 && !turnInProgress && !threadLoading && !threadLoadError && (
            <div className="flex flex-1 flex-col justify-center">
              <WelcomeMessage />
            </div>
          )}
          {messages.map((m, i) => (
            <MessageBubbleRow key={m.id ?? `pending-${i}`} message={m} />
          ))}
          {Object.entries(streaming).map(([id, text]) => (
            <AssistantBubble key={id} content={text} streaming />
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
            <JobApprovalCard pending={pendingApproval} threadId={activeThreadId} />
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
        stopRequested={stopRequested}
      />
    </div>
  );
}
