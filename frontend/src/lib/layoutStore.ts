import { create } from "zustand";
import { persist } from "zustand/middleware";

interface LayoutState {
  leftRailCollapsed: boolean;
  rightDockCollapsed: boolean;
  moleculeCollapsed: boolean;
  jobsCollapsed: boolean;
  jobManagerCollapsed: boolean;
  toggleLeftRail: () => void;
  toggleRightDock: () => void;
  toggleMolecule: () => void;
  toggleJobs: () => void;
  toggleJobManager: () => void;
}

// Panel collapse state persists across reloads (localStorage) but is purely
// local UI state -- never synced to the server, unlike everything in
// chatStore/jobsStore.
export const useLayoutStore = create<LayoutState>()(
  persist(
    (set) => ({
      leftRailCollapsed: false,
      rightDockCollapsed: false,
      moleculeCollapsed: false,
      jobsCollapsed: false,
      jobManagerCollapsed: false,
      toggleLeftRail: () => set((s) => ({ leftRailCollapsed: !s.leftRailCollapsed })),
      toggleRightDock: () => set((s) => ({ rightDockCollapsed: !s.rightDockCollapsed })),
      toggleMolecule: () => set((s) => ({ moleculeCollapsed: !s.moleculeCollapsed })),
      toggleJobs: () => set((s) => ({ jobsCollapsed: !s.jobsCollapsed })),
      toggleJobManager: () => set((s) => ({ jobManagerCollapsed: !s.jobManagerCollapsed })),
    }),
    { name: "qc-agent-layout" },
  ),
);
