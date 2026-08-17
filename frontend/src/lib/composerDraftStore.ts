import { create } from "zustand";

interface ComposerDraftState {
  /** Text to push into the composer, or null when there is nothing pending. */
  draft: string | null;
  /** Monotonic counter, incremented on every setDraft. */
  nonce: number;
  setDraft: (text: string) => void;
  clearDraft: () => void;
}

// Lets something outside the composer put text *into* it -- currently the
// example prompts on the welcome screen. Deliberately NOT persisted, and
// deliberately a prefill rather than a send: a newcomer clicking "Optimise
// the geometry of caffeine" should get a chance to read and edit it before
// committing, and it doubles as a way to learn the phrasing this agent
// understands.
//
// `nonce` exists because the draft alone is not enough to drive an effect.
// Clicking the same example twice in a row leaves `draft` at an identical
// string, so a `useEffect` keyed on the text would not re-fire and the
// second click would appear to do nothing. Keying on the counter instead
// makes every click distinct.
export const useComposerDraftStore = create<ComposerDraftState>((set) => ({
  draft: null,
  nonce: 0,
  setDraft: (text) => set((s) => ({ draft: text, nonce: s.nonce + 1 })),
  clearDraft: () => set({ draft: null }),
}));
