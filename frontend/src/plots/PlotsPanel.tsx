import { useState } from "react";
import { Download, Paperclip } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../lib/api";
import { plotImageUrl, plotDownloadUrl } from "../lib/api";
import { plotsQueryKey, usePlotsQuery } from "../lib/queries";
import { useAttachedPlotsStore } from "../lib/attachedPlotsStore";
import { SearchableText } from "../app-shell/SearchableText";
import { DeletePlotButton } from "./DeletePlotButton";

function relativeTime(epochSeconds: number | null): string {
  if (!epochSeconds) return "";
  const diffSec = Date.now() / 1000 - epochSeconds;
  if (diffSec < 5) return "now";
  if (diffSec < 60) return `${Math.floor(diffSec)}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

// How a row describes where a plot came from. A composed chart is described
// by how many calculations it draws on, since that is the thing a user has to
// tell two similar comparisons apart; a spectrum belongs to exactly one job
// and says so by naming its kind.
function provenance(plot: api.PlotRow): string {
  if (plot.kind === "custom") {
    return plot.job_ids.length === 1 ? "1 job" : `${plot.job_ids.length} jobs`;
  }
  return plot.kind;
}

// Every chart the app has drawn, in one place: the ones the agent composed on
// request and the spectra jobs produce on their own. Selecting rows and
// hitting "Attach to prompt" feeds plot_ids into the Composer via
// attachedPlotsStore, which is how the agent can be asked about a plot or
// asked to edit one without the user quoting its id.
export function PlotsPanel() {
  const plotsQuery = usePlotsQuery();
  const queryClient = useQueryClient();
  const { attachedPlots, addPlot } = useAttachedPlotsStore();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const renameMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) => api.renamePlot(id, label),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: plotsQueryKey }),
  });

  const plots = plotsQuery.data ?? [];
  const attachedIds = new Set(attachedPlots.map((p) => p.plot_id));

  const toggleSelected = (plotId: string) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(plotId)) next.delete(plotId);
      else next.add(plotId);
      return next;
    });
  };

  const attachSelected = () => {
    for (const plot of plots) {
      if (selected.has(plot.plot_id)) addPlot({ plot_id: plot.plot_id, label: plot.label || plot.plot_id });
    }
    setSelected(new Set());
  };

  if (plotsQuery.isLoading) {
    return (
      <div className="flex flex-col gap-1 px-3 py-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton-shimmer h-12 rounded" />
        ))}
      </div>
    );
  }

  if (plotsQuery.isError) {
    return <div className="px-3 py-2 text-xs text-status-failed">Could not load plots.</div>;
  }

  if (plots.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-text-muted">
        No plots yet. Ask for one, or run a job that produces a spectrum.
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-col overflow-y-auto">
      {selected.size > 0 && (
        <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
          <button
            onClick={attachSelected}
            className="flex items-center gap-1 rounded bg-accent px-2 py-1 text-xs text-white hover:opacity-90"
          >
            <Paperclip size={11} />
            Attach to prompt ({selected.size})
          </button>
        </div>
      )}
      <ul className="flex flex-col">
        {plots.map((plot) => {
          const latest = plot.versions[plot.versions.length - 1];
          return (
            <li
              key={plot.plot_id}
              className="flex items-center gap-2 border-b border-border px-3 py-2 last:border-b-0 hover:bg-surface-raised"
            >
              <input
                type="checkbox"
                checked={selected.has(plot.plot_id)}
                onChange={() => toggleSelected(plot.plot_id)}
                aria-label={`Select ${plot.label}`}
                data-testid={`plot-select-${plot.plot_id}`}
                className="shrink-0"
              />
              {latest ? (
                <img
                  src={plotImageUrl(plot.plot_id, latest)}
                  alt=""
                  className="h-10 w-14 shrink-0 rounded border border-border bg-white object-cover"
                />
              ) : (
                <div className="h-10 w-14 shrink-0 rounded border border-border bg-surface" />
              )}
              <div className="min-w-0 flex-1">
                {renamingId === plot.plot_id ? (
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={() => {
                      renameMutation.mutate({ id: plot.plot_id, label: renameValue });
                      setRenamingId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") e.currentTarget.blur();
                      if (e.key === "Escape") setRenamingId(null);
                    }}
                    className="w-full rounded border border-border bg-bg px-1 py-0.5 text-xs text-text"
                  />
                ) : (
                  <div
                    onDoubleClick={() => {
                      setRenamingId(plot.plot_id);
                      setRenameValue(plot.label);
                    }}
                    title={`${plot.label} (double-click to rename)`}
                    className="truncate text-xs text-text"
                    data-testid={`plot-label-${plot.plot_id}`}
                  >
                    <SearchableText text={plot.label} />
                  </div>
                )}
                <div className="truncate text-[11px] text-text-muted">
                  {provenance(plot)}
                  {plot.versions.length > 1 && ` · edited ${plot.versions.length - 1}x`}
                  {` · ${relativeTime(plot.updated_at)}`}
                  {attachedIds.has(plot.plot_id) && " · attached"}
                </div>
              </div>
              <a
                href={plotDownloadUrl(plot.plot_id)}
                download
                onClick={(e) => e.stopPropagation()}
                data-testid={`plot-download-${plot.plot_id}`}
                className="shrink-0 rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
                title="Download plot"
              >
                <Download size={12} />
              </a>
              <DeletePlotButton plotId={plot.plot_id} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
