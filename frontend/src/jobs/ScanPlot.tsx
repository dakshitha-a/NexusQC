import { useState } from "react";
import { Download } from "lucide-react";
import { jobArtifactUrl } from "../lib/api";
import type { JobRow } from "../lib/api";
import { MiniLineChart } from "./MiniLineChart";

const HARTREE_TO_EV = 27.211386245988;

/** Mirrors app/chemistry/jobs/scan_orchestrator.py's _build_state_series:
 * one series per electronic state, ground state first, built from
 * job.summary.state_energies_per_image -- a per-image list of per-state
 * absolute Hartree energies (or null for a still-pending/failed image),
 * populated incrementally while the scan runs, not just once it
 * completes. */
function buildStateSeries(perImage: (number[] | null)[] | undefined): { label: string; y: (number | null)[] }[] {
  if (!perImage?.length) return [];
  const nStates = Math.max(0, ...perImage.map((s) => (s ? s.length : 0)));
  const series = [];
  for (let i = 0; i < nStates; i += 1) {
    series.push({
      label: i === 0 ? "Ground state" : `State ${i}`,
      y: perImage.map((s) => (s && i < s.length ? s[i] : null)),
    });
  }
  return series;
}

/** Same zero-referencing render_pes_plot (app/chemistry/spectrum.py) uses:
 * one shared zero across every state/image, so multiple states' curves sit
 * on a common, comparable scale rather than each floating at its own
 * absolute energy. */
function toRelativeEV(series: { label: string; y: (number | null)[] }[]): { label: string; y: (number | null)[] }[] {
  const known = series.flatMap((s) => s.y).filter((v): v is number => v != null);
  if (!known.length) return series;
  const zero = Math.min(...known);
  return series.map((s) => ({ label: s.label, y: s.y.map((v) => (v == null ? null : (v - zero) * HARTREE_TO_EV)) }));
}

/** While the scan is still running, artifacts.pes_plot doesn't exist yet
 * (scan_orchestrator only renders it once every image is terminal), so the
 * live MiniLineChart -- built incrementally from state_energies_per_image --
 * is the only view available and is shown here. Once the server-rendered
 * PNG exists, it's shown inline instead (mirrors EnsembleSpectrumPanel's
 * img-plus-download shape), since it's the one true "final plot" rather
 * than a lightweight approximation of it; the mini chart falls back into
 * service only if that image fails to load. */
export function ScanPlot({ job }: { job: JobRow }) {
  const [imgFailed, setImgFailed] = useState(false);
  const coordinateValues = (job.summary?.["coordinate_values"] as number[] | undefined) ?? [];
  const coordinateLabel = (job.summary?.["coordinate"] as string | undefined) ?? "coordinate";
  const perImage = job.summary?.["state_energies_per_image"] as (number[] | null)[] | undefined;
  const relative = job.summary?.["relative_energies_eV"] as (number | null)[] | undefined;
  const energies = job.summary?.["energies_hartree"] as (number | null)[] | undefined;

  const stateSeries = toRelativeEV(buildStateSeries(perImage));
  // Falls back to the plain ground-state-only series (energies_hartree/
  // relative_energies_eV) when state_energies_per_image isn't
  // populated at all -- an older job's summary, or a job type
  // _state_energies_hartree doesn't recognize -- rather than showing
  // nothing.
  const fallbackY = relative ?? energies;
  const series = stateSeries.length
    ? stateSeries
    : fallbackY
      ? [{ label: relative ? "Relative energy" : "Energy", y: fallbackY }]
      : [];

  const hasPlot = typeof job.artifacts?.pes_plot === "string";

  if (!series.length || coordinateValues.length === 0) return null;

  if (hasPlot && !imgFailed) {
    return (
      <div className="flex flex-col gap-1.5">
        <img
          src={jobArtifactUrl(job.job_id, "pes_plot")}
          alt="Potential energy surface plot"
          onError={() => setImgFailed(true)}
          className="w-full rounded border border-border bg-white"
        />
        <a
          href={jobArtifactUrl(job.job_id, "pes_plot")}
          download
          className="flex w-fit items-center gap-1 text-[11px] text-text-muted hover:text-text"
        >
          <Download size={11} />
          Download PNG
        </a>
      </div>
    );
  }

  return (
    <MiniLineChart
      x={coordinateValues}
      series={series}
      xLabel={coordinateLabel}
      yLabel={stateSeries.length || relative ? "Relative energy (eV)" : "Energy (Eh)"}
      yBaselineZero={false}
    />
  );
}
