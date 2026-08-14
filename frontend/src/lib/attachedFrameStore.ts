import { create } from "zustand";

export interface AttachedFrame {
  frame_id: string;
  label: string;
}

interface AttachedFrameState {
  attachedFrame: AttachedFrame | null;
  setAttachedFrame: (frame: AttachedFrame) => void;
  clearAttachedFrame: () => void;
}

// Deliberately NOT persisted, same reasoning as attachedJobsStore -- a
// one-shot "use this geometry for my next message" gesture scoped to
// whatever's currently in the composer. Only one frame can be attached at
// a time (unlike attachedJobsStore's multi-select list): a job runs
// against a single active molecule, so "attach frame" always means
// "replace the active molecule with this one" for the next turn, not a
// list to merge -- see set_active_frame's docstring in app/agent/graph.py.
export const useAttachedFrameStore = create<AttachedFrameState>((set) => ({
  attachedFrame: null,
  setAttachedFrame: (frame) => set({ attachedFrame: frame }),
  clearAttachedFrame: () => set({ attachedFrame: null }),
}));
