import { Download } from "lucide-react";
import { jobArtifactUrl } from "../lib/api";
import type { JobRow } from "../lib/api";
import { jobFilenameStem } from "../lib/jobFilename";
import { MiniLineChart } from "./MiniLineChart";

/** Ground-state energy-vs-coordinate trace, live while a scan is still
 * running (job.summary.energies_hartree/coordinate_values are populated
 * incrementally by scan_orchestrator.py as each image's sub-job
 * finishes, with null entries for images still pending/failed -- see
 * MiniLineChart's own NaN-gap handling). Once the whole scan completes,
 * the server-rendered artifacts.pes_plot PNG (one line per electronic
 * state, built by app/chemistry/spectrum.py's render_pes_plot) replaces
 * this as the authoritative view, since it's the only one that shows
 * excited-state curves for a multi-state scan_job_type. */
export function ScanPlot({ job }: { job: JobRow }) {
  const coordinateValues = (job.summary?.["coordinate_values"] as number[] | undefined) ?? [];
  const relative = job.summary?.["relative_energies_kcal_mol"] as (number | null)[] | undefined;
  const energies = job.summary?.["energies_hartree"] as (number | null)[] | undefined;
  const y = relative ?? energies;
  const coordinateLabel = (job.summary?.["coordinate"] as string | undefined) ?? "coordinate";

  const hasPlot = typeof job.artifacts?.pes_plot === "string";

  return (
    <div className="flex flex-col gap-2">
      {!hasPlot && y && coordinateValues.length === y.length && (
        <MiniLineChart
          x={coordinateValues}
          y={y.map((v) => (v == null ? NaN : v))}
          xLabel={coordinateLabel}
          yLabel={relative ? "Relative energy (kcal/mol)" : "Energy (Eh)"}
          yBaselineZero={false}
        />
      )}
      {hasPlot && (
        <div className="flex flex-col gap-1">
          <img
            src={jobArtifactUrl(job.job_id, "pes_plot")}
            alt="PES scan plot"
            className="w-full rounded border border-border bg-white"
          />
          <a
            href={jobArtifactUrl(job.job_id, "pes_plot")}
            download={`${jobFilenameStem(job)}_pes_plot.png`}
            className="flex w-fit items-center gap-1 text-[11px] text-text-muted hover:text-text"
          >
            <Download size={11} />
            Download PNG
          </a>
        </div>
      )}
    </div>
  );
}
