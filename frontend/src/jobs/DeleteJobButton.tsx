import { useState } from "react";
import { Trash2, Check, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { jobsListQueryKey, jobsQuotaQueryKey } from "../lib/queries";

// Deleting a job is irreversible (removes its whole directory from disk),
// unlike cancelling -- gated behind an explicit two-click confirm rather
// than firing on the first click like KillButton does.
export function DeleteJobButton({ jobId, disabled }: { jobId: string; disabled?: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: jobsListQueryKey });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: jobsQuotaQueryKey });
    },
  });

  if (confirming) {
    return (
      <span className="flex shrink-0 items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => deleteMutation.mutate()}
          disabled={deleteMutation.isPending}
          className="rounded p-1 text-status-failed hover:bg-status-failed/10"
          title={deleteMutation.isError ? `Failed to delete: ${String(deleteMutation.error)}` : "Confirm delete"}
        >
          <Check size={12} />
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Cancel"
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
      disabled={disabled}
      className="shrink-0 rounded p-1 text-text-muted hover:bg-surface-raised hover:text-status-failed disabled:opacity-25 disabled:hover:bg-transparent disabled:hover:text-text-muted"
      title={disabled ? "Cancel the job before deleting it" : "Delete job"}
    >
      <Trash2 size={12} />
    </button>
  );
}
