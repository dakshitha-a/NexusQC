import { create } from "zustand";

/**
 * What the job manager is currently showing, held outside the panel because
 * the controls that set it are no longer inside it.
 *
 * The search box and the "Show archived" checkbox used to be a row at the top
 * of the panel body. That panel is the instrument dock's only flex-1 pane, so
 * a row spent there is a row of jobs not shown, and the row was there whether
 * or not anyone was filtering. The controls moved into the section's header,
 * which had space going spare; the search INPUT still opens as a row in the
 * body, where it can have the full width, but only while it is in use.
 *
 * Deliberately not persisted, for the reason the original `useState` carried:
 * archiving a finished study is how you get it off this list, and a rail that
 * silently came back a week later showing archived jobs would just look like
 * archiving had stopped working. The same argument applies to a status filter
 * left on by accident.
 */
export interface JobFilterState {
  query: string;
  searchOpen: boolean;
  showArchived: boolean;
  /** Empty means "no narrowing", not "show nothing". */
  statuses: string[];
  engines: string[];
  setQuery: (query: string) => void;
  setSearchOpen: (open: boolean) => void;
  setShowArchived: (show: boolean) => void;
  toggleStatus: (status: string) => void;
  toggleEngine: (engine: string) => void;
  clearFilters: () => void;
}

const toggle = (list: string[], value: string) =>
  list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

export const useJobFilterStore = create<JobFilterState>()((set) => ({
  query: "",
  searchOpen: false,
  showArchived: false,
  statuses: [],
  engines: [],
  setQuery: (query) => set({ query }),
  setSearchOpen: (searchOpen) => set({ searchOpen }),
  setShowArchived: (showArchived) => set({ showArchived }),
  toggleStatus: (status) => set((s) => ({ statuses: toggle(s.statuses, status) })),
  toggleEngine: (engine) => set((s) => ({ engines: toggle(s.engines, engine) })),
  clearFilters: () => set({ statuses: [], engines: [] }),
}));
