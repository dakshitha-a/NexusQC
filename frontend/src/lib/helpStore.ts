import { create } from "zustand";
import { persist } from "zustand/middleware";

interface HelpState {
  /** Whether the tutorial flyout is showing. Not persisted -- reopening the
   *  app should not reopen a panel you closed. */
  helpOpen: boolean;
  /** Whether this browser has ever opened the tutorial. Persisted, so the
   *  first-run hint appears once and then stops nagging. */
  tutorialSeen: boolean;
  openHelp: () => void;
  closeHelp: () => void;
  dismissHint: () => void;
}

// Help open-state used to be a plain useState inside LeftRail, which made the
// tutorial unreachable from anywhere else -- including the welcome screen,
// which is exactly where a newcomer is standing when they need it. Lifting it
// into a store is what lets both the rail button and the welcome screen open
// the same panel.
export const useHelpStore = create<HelpState>()(
  persist(
    (set) => ({
      helpOpen: false,
      tutorialSeen: false,
      // Opening the tutorial by any route counts as having seen it.
      openHelp: () => set({ helpOpen: true, tutorialSeen: true }),
      closeHelp: () => set({ helpOpen: false }),
      dismissHint: () => set({ tutorialSeen: true }),
    }),
    {
      name: "nexusqc-help",
      // Only the "have they seen it" flag survives a reload.
      partialize: (s) => ({ tutorialSeen: s.tutorialSeen }) as HelpState,
    },
  ),
);
