import { create } from "zustand";
import { persist } from "zustand/middleware";

interface LayoutState {
  leftRailCollapsed: boolean;
  rightDockCollapsed: boolean;
  moleculeCollapsed: boolean;
  jobsCollapsed: boolean;
  jobManagerCollapsed: boolean;
  leftRailWidth: number;
  rightDockWidth: number;
  toggleLeftRail: () => void;
  toggleRightDock: () => void;
  toggleMolecule: () => void;
  toggleJobs: () => void;
  toggleJobManager: () => void;
  setLeftRailWidth: (width: number) => void;
  setRightDockWidth: (width: number) => void;
}

// Drag bounds for the two resize handles in ShellLayout. Kept generous
// enough that a user can shrink a panel down to its icon-strip-ish minimum
// or widen it to take up most of a normal laptop screen, but never so far
// that it swallows the whole window -- ChatPane always keeps some room
// since it isn't shrink-0 and has its own min-w-0 (see ShellLayout/
// ChatPane for the overflow fix these bounds pair with).
export const LEFT_RAIL_MIN = 220;
export const LEFT_RAIL_MAX = 520;
export const RIGHT_DOCK_MIN = 280;
export const RIGHT_DOCK_MAX = 720;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

// Panel collapse/width state persists across reloads (localStorage) but is
// purely local UI state -- never synced to the server, unlike everything in
// chatStore/jobsStore.
export const useLayoutStore = create<LayoutState>()(
  persist(
    (set) => ({
      leftRailCollapsed: false,
      rightDockCollapsed: false,
      moleculeCollapsed: false,
      jobsCollapsed: false,
      jobManagerCollapsed: false,
      leftRailWidth: 288,
      rightDockWidth: 420,
      toggleLeftRail: () => set((s) => ({ leftRailCollapsed: !s.leftRailCollapsed })),
      toggleRightDock: () => set((s) => ({ rightDockCollapsed: !s.rightDockCollapsed })),
      toggleMolecule: () => set((s) => ({ moleculeCollapsed: !s.moleculeCollapsed })),
      toggleJobs: () => set((s) => ({ jobsCollapsed: !s.jobsCollapsed })),
      toggleJobManager: () => set((s) => ({ jobManagerCollapsed: !s.jobManagerCollapsed })),
      setLeftRailWidth: (width) => set({ leftRailWidth: clamp(width, LEFT_RAIL_MIN, LEFT_RAIL_MAX) }),
      setRightDockWidth: (width) => set({ rightDockWidth: clamp(width, RIGHT_DOCK_MIN, RIGHT_DOCK_MAX) }),
    }),
    { name: "qc-agent-layout" },
  ),
);
