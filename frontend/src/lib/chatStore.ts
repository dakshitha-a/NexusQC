import { create } from "zustand";
import type { ChatMessage, MoleculeDict, MoleculeFrame, PendingApproval } from "./api";

export interface AgentStep {
  node: "agent" | "tools";
  toolName: string;
  phase: "started" | "finished";
}

interface SSEEvent {
  type: string;
  [key: string]: unknown;
}

interface ChatState {
  threadId: string | null;
  messages: ChatMessage[];
  /** message_id -> accumulated delta text, for an assistant message still
   * streaming (not yet finalized by a "message" event). */
  streaming: Record<string, string>;
  pendingApproval: PendingApproval | null;
  turnInProgress: boolean;
  activeSteps: AgentStep[];
  error: string | null;
  molecule: MoleculeDict | null;
  /** Every molecule the user has explicitly set, in order -- backs the
   * molecule panel's frame slider/attach-to-prompt UI. See
   * app/agent/state.py's molecule_frames for the backend side. */
  moleculeFrames: MoleculeFrame[];
  /** True once the SSE connection for the active thread is actually open.
   * The composer must not allow sending until this is true: SSEHub.publish
   * (server/sse.py) is fire-and-forget with no event replay, so a message
   * posted before the EventSource finishes connecting would have its
   * entire turn -- including the turn_complete that clears turnInProgress
   * -- silently dropped, leaving the composer disabled forever with no
   * recovery short of a reload (confirmed empirically). */
  sseConnected: boolean;
  /** True once sseConnected has been true at least once for the current
   * thread -- lets the UI distinguish "connecting for the first time"
   * from "the connection that was already up just dropped," which
   * previously looked identical (both just showed "Connecting..."). Reset
   * on loadThread since a thread switch opens a brand-new EventSource. */
  sseHasConnectedOnce: boolean;
  /** True right after the user clicks Stop and until the next turn starts
   * or the thread changes -- drives a small transient "Stopped." note in
   * the chat pane, distinct from turnInProgress (which turn_complete
   * always clears regardless of whether the turn finished normally). */
  lastTurnStopped: boolean;
  /** Why the last Approve/Run-edited click was rejected, shown inline on
   * the approval card itself. This has to live in the store rather than in
   * JobApprovalCard's own useMutation state: dismissPendingApproval
   * unmounts that card the instant the button is clicked, so any error
   * state held inside it is destroyed before onError can restore the card
   * and would be gone from the freshly-mounted copy. Cleared whenever a
   * new attempt starts or the thread changes. */
  approvalError: string | null;
  /** True while an existing conversation's state is being fetched.
   *
   * GET /api/threads/{id}/state takes that thread's own lock, so opening a
   * conversation whose agent turn is currently running blocks until that
   * turn finishes -- measured at 19.5s for an ordinary turn, and far
   * longer for job_watcher's investigate-and-retry turn (check_job_status,
   * a KB search, possibly web_search, then submit_job). Without this flag
   * the pane rendered its "start a new conversation" welcome screen for
   * that entire wait, because the store is deliberately cleared to empty
   * before the fetch (to stop the previous thread's messages flashing
   * under the new thread's identity). A user coming back to a conversation
   * whose job had just failed would see what looked like an empty one. */
  threadLoading: boolean;
  threadLoadError: string | null;
  setThreadLoading: (loading: boolean, error?: string | null) => void;

  loadThread: (
    threadId: string,
    messages: ChatMessage[],
    pendingApproval: PendingApproval | null,
    molecule: MoleculeDict | null,
    moleculeFrames: MoleculeFrame[],
  ) => void;
  applyEvent: (event: SSEEvent) => void;
  clearError: () => void;
  optimisticUserMessage: (text: string) => void;
  setMolecule: (molecule: MoleculeDict | null) => void;
  setMoleculeFrames: (frames: MoleculeFrame[]) => void;
  setSseConnected: (connected: boolean) => void;
  /** Hides the approval card the instant the user clicks Approve/Reject,
   * rather than waiting for resume_turn's response -- that's a single
   * blocking graph.invoke() covering job resubmission plus a full
   * follow-up LLM turn (see server/routes/chat.py's approval routes and
   * graph.py's resume_turn docstring), easily a few seconds, and the card
   * has nothing left to show once the user has made their choice. Returns
   * the previous value so a failed request can restore it. */
  dismissPendingApproval: () => PendingApproval | null;
}

export const useChatStore = create<ChatState>((set, get) => ({
  threadId: null,
  messages: [],
  streaming: {},
  pendingApproval: null,
  turnInProgress: false,
  activeSteps: [],
  error: null,
  molecule: null,
  moleculeFrames: [],
  sseConnected: false,
  sseHasConnectedOnce: false,
  lastTurnStopped: false,
  approvalError: null,
  threadLoading: false,
  threadLoadError: null,

  setThreadLoading: (threadLoading, threadLoadError = null) =>
    set({ threadLoading, threadLoadError }),

  loadThread: (threadId, messages, pendingApproval, molecule, moleculeFrames) =>
    set({
      threadId,
      messages,
      pendingApproval,
      molecule,
      moleculeFrames,
      streaming: {},
      turnInProgress: false,
      activeSteps: [],
      error: null,
      lastTurnStopped: false,
      sseHasConnectedOnce: false,
      approvalError: null,
      threadLoadError: null,
    }),

  setMolecule: (molecule) => set({ molecule }),
  setMoleculeFrames: (moleculeFrames) => set({ moleculeFrames }),
  setSseConnected: (connected) =>
    set((s) => ({ sseConnected: connected, sseHasConnectedOnce: s.sseHasConnectedOnce || connected })),

  // Renders the user's own message immediately on send, before the server
  // round-trip -- same fix as this app's Streamlit predecessor (see
  // CLAUDE.md: rendering the user's chat_message before the turn runs was
  // what fixed the "my prompt doesn't show up until the response arrives"
  // complaint). The real HumanMessage arrives moments later via the
  // "message" SSE event and (matching by content+recency, not id, since
  // this optimistic one has no server-assigned id) is left in place --
  // duplicate suppression happens in applyEvent's HumanMessage handling.
  optimisticUserMessage: (text) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: null, type: "HumanMessage", content: text, name: null, tool_call_id: null, tool_calls: [] },
      ],
      turnInProgress: true,
      lastTurnStopped: false,
    })),

  applyEvent: (event) =>
    set((s) => {
      switch (event.type) {
        case "token": {
          const messageId = event.message_id as string;
          const delta = event.delta as string;
          return {
            turnInProgress: true,
            streaming: { ...s.streaming, [messageId]: (s.streaming[messageId] ?? "") + delta },
          };
        }
        case "agent_step": {
          const step: AgentStep = {
            node: event.node as AgentStep["node"],
            toolName: event.tool_name as string,
            phase: event.phase as AgentStep["phase"],
          };
          if (step.phase === "started") {
            return { turnInProgress: true, activeSteps: [...s.activeSteps, step] };
          }
          return {
            turnInProgress: true,
            activeSteps: s.activeSteps.filter((st) => st.toolName !== step.toolName || st.phase !== "started"),
          };
        }
        case "message": {
          const incoming = event.message as ChatMessage;
          const streaming = { ...s.streaming };
          if (incoming.id) delete streaming[incoming.id];

          // A HumanMessage that just arrived from the server matches (by
          // content) the optimistic placeholder rendered on send -- replace
          // the placeholder (id: null) rather than showing the message
          // twice.
          if (incoming.type === "HumanMessage") {
            const placeholderIdx = s.messages.findIndex((m) => m.id === null && m.content === incoming.content);
            if (placeholderIdx !== -1) {
              const messages = [...s.messages];
              messages[placeholderIdx] = incoming;
              return { messages, streaming };
            }
          }

          const existingIdx = incoming.id ? s.messages.findIndex((m) => m.id === incoming.id) : -1;
          if (existingIdx !== -1) {
            const messages = [...s.messages];
            messages[existingIdx] = incoming;
            return { messages, streaming };
          }
          return { messages: [...s.messages, incoming], streaming };
        }
        case "interrupt":
          return { pendingApproval: (event.interrupt as PendingApproval | null) ?? null };
        case "turn_complete":
          return {
            turnInProgress: false,
            activeSteps: [],
            streaming: {},
            lastTurnStopped: !!event.stopped,
          };
        case "error":
          return { turnInProgress: false, error: event.message as string };
        default:
          return {};
      }
    }),

  clearError: () => set({ error: null }),

  dismissPendingApproval: () => {
    const previous = get().pendingApproval;
    // turnInProgress mirrors optimisticUserMessage's reasoning: without
    // it, the composer would briefly re-enable (pendingApproval is now
    // false, and no SSE event has set turnInProgress yet) during the gap
    // before resume_turn's turn_complete arrives.
    set({ pendingApproval: null, turnInProgress: true, lastTurnStopped: false, approvalError: null });
    return previous;
  },
}));
