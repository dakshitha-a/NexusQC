import { create } from "zustand";

interface AttachedPlot {
  plot_id: string;
  label: string;
}

interface AttachedPlotsState {
  attachedPlots: AttachedPlot[];
  addPlot: (plot: AttachedPlot) => void;
  removePlot: (plotId: string) => void;
  clear: () => void;
}

// Deliberately not persisted, for the same reason attachedJobsStore isn't: an
// attachment is a one-shot gesture scoped to whatever is currently in the
// composer, not a preference. Reloading mid-compose should not silently
// re-attach plots to a message the user has since rewritten.
export const useAttachedPlotsStore = create<AttachedPlotsState>((set) => ({
  attachedPlots: [],
  addPlot: (plot) =>
    set((s) => (s.attachedPlots.some((p) => p.plot_id === plot.plot_id) ? s : { attachedPlots: [...s.attachedPlots, plot] })),
  removePlot: (plotId) => set((s) => ({ attachedPlots: s.attachedPlots.filter((p) => p.plot_id !== plotId) })),
  clear: () => set({ attachedPlots: [] }),
}));
