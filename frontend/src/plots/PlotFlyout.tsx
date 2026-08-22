import { Flyout } from "../app-shell/Flyout";
import { DownloadButton } from "../app-shell/DownloadButton";
import { triggerDownload } from "../lib/download";
import { plotDownloadUrl, plotImageUrl } from "../lib/api";
import { usePlotQuery } from "../lib/queries";
import { useState } from "react";

// Six significant figures, trailing zeros trimmed. The stored values carry
// full float precision (11.37654495724591), which is right for the record and
// unreadable in a table -- and misleading, since nothing about a TDDFT
// excitation energy is meaningful to fourteen digits.
function formatValue(v: number | null): string {
  if (v === null || v === undefined) return "";
  if (!Number.isFinite(v)) return String(v);
  return String(Number(v.toPrecision(6)));
}

// The enlarged view of one saved plot, opened by clicking its row in the
// Plots panel. Same Flyout the job drawer and the file preview use, so the
// enlarge gesture behaves identically wherever it appears.
//
// It shows more than a bigger picture. A plot is a saved recipe plus the
// numbers it drew (app/plots/store.py), and both are worth seeing: the
// numbers are what the agent is given when the plot is attached to a prompt,
// so a user comparing what it said against what it saw needs the same table.
export function PlotFlyout({ plotId, onClose }: { plotId: string; onClose: () => void }) {
  const detailQuery = usePlotQuery(plotId);
  const plot = detailQuery.data;
  // Which rendered version is on screen. Defaults to the latest; the older
  // ones are kept precisely so an edit does not destroy what an earlier
  // message in the conversation was talking about, which makes them worth
  // being able to look at.
  const [version, setVersion] = useState<string | null>(null);
  const versions = plot?.versions ?? [];
  const shown = version && versions.includes(version) ? version : versions[versions.length - 1];

  const columns = (plot?.data?.columns as string[] | undefined) ?? null;
  const series = (plot?.data?.series as Record<string, (number | null)[]> | undefined) ?? null;

  return (
    <Flyout
      open
      onClose={onClose}
      title={plot?.label ?? "Plot"}
      widthClassName="w-160"
      headerActions={
        <DownloadButton
          title={`Download ${plot?.label ?? "plot"}`}
          testId="flyout-download-plot"
          onDownload={() => triggerDownload(plotDownloadUrl(plotId))}
        />
      }
    >
      {detailQuery.isLoading && <div className="skeleton-shimmer h-64 rounded" />}
      {detailQuery.isError && <div className="text-xs text-status-failed">Could not load this plot.</div>}
      {plot && (
        <div className="flex flex-col gap-3">
          {shown ? (
            <img
              src={plotImageUrl(plotId, shown)}
              alt={plot.label}
              data-testid="plot-flyout-image"
              className="w-full rounded border border-border bg-white"
            />
          ) : (
            <div className="rounded border border-border px-3 py-6 text-center text-xs text-text-muted">
              This plot has no rendered image.
            </div>
          )}

          {versions.length > 1 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="mr-1 text-[11px] text-text-muted">Versions:</span>
              {versions.map((v) => (
                <button
                  key={v}
                  onClick={() => setVersion(v)}
                  data-testid={`plot-version-${v}`}
                  className={`rounded px-1.5 py-0.5 text-[11px] ${
                    v === shown ? "bg-accent text-white" : "bg-surface-raised text-text-muted hover:text-text"
                  }`}
                  title={v === versions[versions.length - 1] ? "Latest" : "An earlier render, kept so older messages still show what they described"}
                >
                  {v}
                </button>
              ))}
            </div>
          )}

          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px] text-text-muted">
            <dt>Kind</dt>
            <dd className="text-text">{String(plot.spec?.style ?? plot.kind)}</dd>
            <dt>From</dt>
            <dd className="break-all text-text">{plot.job_ids.join(", ") || "no jobs recorded"}</dd>
            <dt>Plot id</dt>
            <dd className="text-text">{plot.plot_id}</dd>
          </dl>

          {columns && series && (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[11px]">
                <thead>
                  <tr>
                    <th className="border border-border px-2 py-1 text-left text-text-muted"> </th>
                    {columns.map((c) => (
                      <th key={c} className="border border-border px-2 py-1 text-left text-text-muted">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(series).map(([name, values]) => (
                    <tr key={name}>
                      <td className="border border-border px-2 py-1 text-text">{name}</td>
                      {values.map((v, i) => (
                        <td key={i} className="border border-border px-2 py-1 tabular-nums text-text">
                          {formatValue(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Flyout>
  );
}
