import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ActiveThreadState {
  activeThreadId: string | null;
  setActiveThreadId: (id: string | null) => void;
}

// Persisted so a page reload stays on the same conversation -- the actual
// conversation history/state itself always comes from the server
// (GET /state), this just remembers which one was open.
export const useActiveThreadStore = create<ActiveThreadState>()(
  persist(
    (set) => ({
      activeThreadId: null,
      setActiveThreadId: (id) => set({ activeThreadId: id }),
    }),
    { name: "qc-agent-active-thread" },
  ),
);
