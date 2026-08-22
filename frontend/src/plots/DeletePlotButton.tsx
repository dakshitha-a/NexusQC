import { useState } from "react";
import { Trash2, Check, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { plotsQueryKey } from "../lib/queries";

// Two-click confirm, matching DeleteJobButton. Deleting a plot is less
// destructive than deleting a job (the underlying job data is untouched, so
// the same plot can be asked for again), but it still removes something the
// user made and it sits one pixel from the download button.
export function DeletePlotButton({ plotId }: { plotId: string }) {
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: () => api.deletePlot(plotId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: plotsQueryKey }),
  });

  if (confirming) {
    return (
      <span className="flex shrink-0 items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => deleteMutation.mutate()}
          disabled={deleteMutation.isPending}
          data-testid={`plot-delete-confirm-${plotId}`}
          className="rounded p-1 text-status-failed hover:bg-status-failed/10"
          title={deleteMutation.isError ? `Failed to delete: ${String(deleteMutation.error)}` : "Confirm delete"}
        >
          <Check size={12} />
        </button>
        <button
          onClick={() => setConfirming(false)}
          data-testid={`plot-delete-dismiss-${plotId}`}
          className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
          title="Don't delete"
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
      data-testid={`plot-delete-${plotId}`}
      className="shrink-0 rounded p-1 text-text-muted hover:bg-surface-raised hover:text-status-failed"
      title="Delete plot"
    >
      <Trash2 size={12} />
    </button>
  );
}
