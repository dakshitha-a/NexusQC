import { Download } from "lucide-react";
import { jobArtifactUrl } from "../lib/api";
import type { JobRow } from "../lib/api";

/** Server-rendered reaction-path plot (app/chemistry/spectrum.py's
 * render_neb_plot, written by orca_runner.run_neb_ts once the job
 * completes) -- unlike pes_scan's ScanPlot, there's no live inline chart
 * while running, since neb_ts is a single opaque ORCA job with no
 * incrementally-updated energy series to draw (see LiveLogPanel/
 * NebFrameViewer's live geometry view for what IS available mid-run). */
export function NebEnergyPlot({ job }: { job: JobRow }) {
  const hasPlot = typeof job.artifacts?.neb_plot === "string";

  if (!hasPlot) {
    return (
      <div className="text-xs text-text-muted">
        {job.status === "running"
          ? "The reaction-path plot will be available once the job completes."
          : "No plot available -- no PATH SUMMARY table was found in the output (see the summary note)."}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <img
        src={jobArtifactUrl(job.job_id, "neb_plot")}
        alt="NEB-TS reaction path plot"
        className="w-full rounded border border-border bg-white"
      />
      <a
        href={jobArtifactUrl(job.job_id, "neb_plot")}
        download={`${job.job_id}_neb_plot.png`}
        className="flex w-fit items-center gap-1 text-[11px] text-text-muted hover:text-text"
      >
        <Download size={11} />
        Download PNG
      </a>
    </div>
  );
}
