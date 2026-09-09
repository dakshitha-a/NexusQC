import { create } from "zustand";

/**
 * The plots drawer's filter, held outside the panel for the same reason the
 * job manager's is: the control that opens it lives in the section header,
 * which RightDock renders, and the input opens as a row in the body.
 *
 * A separate store from jobFilterStore rather than a shared keyed one. Two
 * panels is not a pattern, and the job manager's also carries status and
 * engine selections that mean nothing here.
 *
 * Not persisted. A filter left on by accident turns a short list into a bug
 * report, and this one is cheap to retype.
 */
interface PlotFilterState {
  query: string;
  open: boolean;
  setQuery: (query: string) => void;
  setOpen: (open: boolean) => void;
}

export const usePlotFilterStore = create<PlotFilterState>()((set) => ({
  query: "",
  open: false,
  setQuery: (query) => set({ query }),
  setOpen: (open) => set({ open }),
}));
