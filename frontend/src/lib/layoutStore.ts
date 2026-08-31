import { create } from "zustand";
import { persist } from "zustand/middleware";

/** The left rail's sections, in the order they are stacked. Conversations
 *  has no collapse state of its own -- it is always open, since it is what
 *  the sidebar is primarily for -- but it is nameable here so the collapsed
 *  rail's icon for it can still expand the rail and scroll to it. */
export type LeftRailSection = "conversations" | "kb" | "files" | "projects";

interface LayoutState {
  leftRailCollapsed: boolean;
  rightDockCollapsed: boolean;
  moleculeCollapsed: boolean;
  jobsCollapsed: boolean;
  jobManagerCollapsed: boolean;
  plotsCollapsed: boolean;
  // The left rail's own sections. These used to be three separate
  // useState(true) calls inside KbSection/FilesSection/ProjectsSection,
  // which made them unreachable from anywhere else -- including from the
  // collapsed rail's icons, whose whole job is to open one. Lifted here to
  // match how the right dock's sections have always worked, which also
  // means they now persist across a reload like every other panel.
  kbCollapsed: boolean;
  filesCollapsed: boolean;
  projectsCollapsed: boolean;
  leftRailWidth: number;
  rightDockWidth: number;
  toggleLeftRail: () => void;
  toggleRightDock: () => void;
  toggleMolecule: () => void;
  toggleJobs: () => void;
  toggleJobManager: () => void;
  togglePlots: () => void;
  toggleKb: () => void;
  toggleFiles: () => void;
  toggleProjects: () => void;
  /** Expands the rail if it is collapsed and opens the named section, so a
   *  single click on a collapsed-rail icon lands somewhere useful rather
   *  than merely widening the sidebar onto four closed headers. */
  revealLeftRailSection: (section: LeftRailSection) => void;
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
      plotsCollapsed: false,
      // Collapsed to start, all three, which is what they were as local
      // state: Conversations is the one left-rail section always open, and
      // three more expanded below it would push the conversation list off
      // the screen.
      kbCollapsed: true,
      filesCollapsed: true,
      projectsCollapsed: true,
      leftRailWidth: 288,
      rightDockWidth: 420,
      toggleLeftRail: () => set((s) => ({ leftRailCollapsed: !s.leftRailCollapsed })),
      toggleRightDock: () => set((s) => ({ rightDockCollapsed: !s.rightDockCollapsed })),
      toggleMolecule: () => set((s) => ({ moleculeCollapsed: !s.moleculeCollapsed })),
      toggleJobs: () => set((s) => ({ jobsCollapsed: !s.jobsCollapsed })),
      toggleJobManager: () => set((s) => ({ jobManagerCollapsed: !s.jobManagerCollapsed })),
      togglePlots: () => set((s) => ({ plotsCollapsed: !s.plotsCollapsed })),
      toggleKb: () => set((s) => ({ kbCollapsed: !s.kbCollapsed })),
      toggleFiles: () => set((s) => ({ filesCollapsed: !s.filesCollapsed })),
      toggleProjects: () => set((s) => ({ projectsCollapsed: !s.projectsCollapsed })),
      revealLeftRailSection: (section) =>
        set({
          leftRailCollapsed: false,
          ...(section === "kb" ? { kbCollapsed: false } : {}),
          ...(section === "files" ? { filesCollapsed: false } : {}),
          ...(section === "projects" ? { projectsCollapsed: false } : {}),
        }),
      setLeftRailWidth: (width) => set({ leftRailWidth: clamp(width, LEFT_RAIL_MIN, LEFT_RAIL_MAX) }),
      setRightDockWidth: (width) => set({ rightDockWidth: clamp(width, RIGHT_DOCK_MIN, RIGHT_DOCK_MAX) }),
    }),
    { name: "qc-agent-layout" },
  ),
);
