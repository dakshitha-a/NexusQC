import { create } from "zustand";

export interface AttachedJob {
  job_id: string;
  label: string;
}

interface AttachedJobsState {
  attachedJobs: AttachedJob[];
  addJob: (job: AttachedJob) => void;
  removeJob: (jobId: string) => void;
  clear: () => void;
}

// Deliberately NOT persisted (unlike activeThreadStore/layoutStore) -- an
// attachment is a one-shot "include this job's results in my next message"
// gesture scoped to whatever's currently in the composer. Surviving a page
// reload would let a stale attachment silently ride along with an
// unrelated later message.
export const useAttachedJobsStore = create<AttachedJobsState>((set) => ({
  attachedJobs: [],
  addJob: (job) =>
    set((s) =>
      s.attachedJobs.some((j) => j.job_id === job.job_id) ? s : { attachedJobs: [...s.attachedJobs, job] },
    ),
  removeJob: (jobId) => set((s) => ({ attachedJobs: s.attachedJobs.filter((j) => j.job_id !== jobId) })),
  clear: () => set({ attachedJobs: [] }),
}));
