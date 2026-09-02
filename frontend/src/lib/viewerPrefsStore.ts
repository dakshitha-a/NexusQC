import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ViewerPrefsState {
  /** Whether the 3D viewers draw a 1-based number on every atom. */
  atomLabels: boolean;
  toggleAtomLabels: () => void;
}

// What the 3D viewers DRAW, as opposed to layoutStore, which is where the
// panels are and whether they are open. Kept as its own store for that
// reason rather than as two more fields on layoutStore: the two answer
// different questions and nothing reads both.
//
// Persisted, and local-only, for the reason layoutStore gives about panel
// state -- it is a preference about this browser's view of the data, never
// a property of the data, so it does not belong on the server. One switch
// governs every viewer at once because the numbering is a reading aid you
// either want or don't; having it on in the molecule panel and off in the
// orbital viewer is not a state anyone asked for, and per-viewer switches
// would mean finding the right one before every screenshot.
//
// Defaults to on, which is what every viewer did unconditionally before
// this existed, so an upgrade changes nobody's view until they ask it to.
export const useViewerPrefsStore = create<ViewerPrefsState>()(
  persist(
    (set) => ({
      atomLabels: true,
      toggleAtomLabels: () => set((s) => ({ atomLabels: !s.atomLabels })),
    }),
    { name: "qc-agent-viewer-prefs" },
  ),
);
