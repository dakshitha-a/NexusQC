import { Square } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { jobQueryKey, jobsQueryKey } from "../lib/queries";
import type { JobRow } from "../lib/api";

export function KillButton({ job, threadId }: { job: JobRow; threadId: string }) {
  const queryClient = useQueryClient();
  const terminal = job.status === "completed" || job.status === "failed" || job.status === "cancelled";

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelJob(job.job_id),
    onSuccess: (updated) => {
      queryClient.setQueryData(jobQueryKey(job.job_id), updated);
      queryClient.invalidateQueries({ queryKey: jobsQueryKey(threadId) });
    },
  });

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        cancelMutation.mutate();
      }}
      disabled={terminal || cancelMutation.isPending}
      className="shrink-0 rounded p-1 text-text-muted hover:bg-surface-raised hover:text-status-failed disabled:opacity-25 disabled:hover:bg-transparent disabled:hover:text-text-muted"
      title={terminal ? "Job already finished" : cancelMutation.isPending ? "Cancelling..." : "Cancel job"}
    >
      <Square size={12} fill="currentColor" />
    </button>
  );
}
