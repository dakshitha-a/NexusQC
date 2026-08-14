import { create } from "zustand";
import type { ChatMessage, MoleculeDict, PendingApproval } from "./api";

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
  /** True once the SSE connection for the active thread is actually open.
   * The composer must not allow sending until this is true: SSEHub.publish
   * (server/sse.py) is fire-and-forget with no event replay, so a message
   * posted before the EventSource finishes connecting would have its
   * entire turn -- including the turn_complete that clears turnInProgress
   * -- silently dropped, leaving the composer disabled forever with no
   * recovery short of a reload (confirmed empirically). */
  sseConnected: boolean;
  /** True right after the user clicks Stop and until the next turn starts
   * or the thread changes -- drives a small transient "Stopped." note in
   * the chat pane, distinct from turnInProgress (which turn_complete
   * always clears regardless of whether the turn finished normally). */
  lastTurnStopped: boolean;

  loadThread: (
    threadId: string,
    messages: ChatMessage[],
    pendingApproval: PendingApproval | null,
    molecule: MoleculeDict | null,
  ) => void;
  applyEvent: (event: SSEEvent) => void;
  clearError: () => void;
  optimisticUserMessage: (text: string) => void;
  setMolecule: (molecule: MoleculeDict | null) => void;
  setSseConnected: (connected: boolean) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  threadId: null,
  messages: [],
  streaming: {},
  pendingApproval: null,
  turnInProgress: false,
  activeSteps: [],
  error: null,
  molecule: null,
  sseConnected: false,
  lastTurnStopped: false,

  loadThread: (threadId, messages, pendingApproval, molecule) =>
    set({
      threadId,
      messages,
      pendingApproval,
      molecule,
      streaming: {},
      turnInProgress: false,
      activeSteps: [],
      error: null,
      lastTurnStopped: false,
    }),

  setMolecule: (molecule) => set({ molecule }),
  setSseConnected: (connected) => set({ sseConnected: connected }),

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
}));
