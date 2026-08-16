import { useRef, useState } from "react";
import type { JobRow } from "../lib/api";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

// Shared by JobsPanel/JobManagerPanel: a row's status silently re-colors
// when a job finishes (see StatusDot's own color transition), which is
// easy to miss in a list of several rows -- this tracks each job_id's
// previously-seen status across renders and returns the set of ids that
// JUST transitioned into a terminal state, so the caller can apply a
// one-shot flash-once highlight (see index.css) to draw the eye to it.
// The caller clears an id via `clear(jobId)` once its animation ends
// (onAnimationEnd), so the class doesn't get reapplied on every re-render.
export function useFlashOnTerminal(jobs: JobRow[]): { flashing: Set<string>; clear: (jobId: string) => void } {
  const prevStatuses = useRef<Map<string, string>>(new Map());
  const [flashing, setFlashing] = useState<Set<string>>(new Set());

  const newlyTerminal: string[] = [];
  for (const job of jobs) {
    const prev = prevStatuses.current.get(job.job_id);
    if (prev !== undefined && prev !== job.status && TERMINAL.has(job.status) && !flashing.has(job.job_id)) {
      newlyTerminal.push(job.job_id);
    }
    prevStatuses.current.set(job.job_id, job.status);
  }
  if (newlyTerminal.length > 0) {
    // Deferred so this doesn't setState during the render that discovered
    // it -- the next render then includes these ids in `flashing`.
    queueMicrotask(() => setFlashing((prev) => new Set([...prev, ...newlyTerminal])));
  }

  const clear = (jobId: string) =>
    setFlashing((prev) => {
      if (!prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.delete(jobId);
      return next;
    });

  return { flashing, clear };
}
