import { useState } from "react";
import { Square, Check, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { jobQueryKey, jobsListQueryKey, jobsQueryKey } from "../lib/queries";
import type { JobRow } from "../lib/api";

// threadId is optional: the Job Manager panel (JobManagerPanel.tsx) shows
// jobs across every conversation, not just the active one, so a cancel
// triggered from there has no single thread-scoped jobsQueryKey to
// invalidate -- the global jobsListQueryKey invalidation below covers it
// either way.
export function KillButton({ job, threadId }: { job: JobRow; threadId?: string }) {
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();
  const terminal = job.status === "completed" || job.status === "failed" || job.status === "cancelled";

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelJob(job.job_id),
    onSuccess: (updated) => {
      queryClient.setQueryData(jobQueryKey(job.job_id), updated);
      if (threadId) queryClient.invalidateQueries({ queryKey: jobsQueryKey(threadId) });
      queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
    },
  });

  // Same inline two-step confirm as DeleteJobButton -- cancelling has no
  // undo (a killed process can't be resumed), so firing on the first click
  // with no confirmation was a real gap, not just a cosmetic mismatch.
  if (confirming) {
    return (
      <span className="flex shrink-0 items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => {
            cancelMutation.mutate();
            setConfirming(false);
          }}
          data-testid={`job-kill-confirm-${job.job_id}`}
          className="rounded p-1 text-status-failed hover:bg-status-failed/10"
          title="Confirm cancel"
        >
          <Check size={12} />
        </button>
        <button
          onClick={() => setConfirming(false)}
          data-testid={`job-kill-dismiss-${job.job_id}`}
          className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Keep running"
        >
          <X size={12} />
        </button>
      </span>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        setConfirming(true);
      }}
      disabled={terminal || cancelMutation.isPending}
      data-testid={`job-kill-${job.job_id}`}
      className={`shrink-0 rounded p-1 hover:bg-surface-raised hover:text-status-failed disabled:opacity-25 disabled:hover:bg-transparent disabled:hover:text-text-muted ${
        cancelMutation.isError ? "text-status-failed" : "text-text-muted"
      }`}
      title={
        cancelMutation.isError
          ? `Failed to cancel: ${String(cancelMutation.error)}`
          : terminal
            ? "Job already finished"
            : cancelMutation.isPending
              ? "Cancelling..."
              : "Cancel job"
      }
    >
      <Square size={12} fill="currentColor" />
    </button>
  );
}
