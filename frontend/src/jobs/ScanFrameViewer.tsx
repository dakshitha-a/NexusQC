import { useEffect, useState } from "react";
import { jobArtifactUrl } from "../lib/api";
import type { JobRow } from "../lib/api";
import { MoleculeViewer } from "../molecule/MoleculeViewer";
import { moleculeToXyzBlock, parseMultiFrameXyz } from "../molecule/xyz";

/** Multi-frame geometry viewer for a pes_scan master job -- the path is
 * written to disk (artifacts.path_xyz) the instant the scan is approved
 * (see JobManager.submit_scan), so this renders immediately even while
 * every image's own sub-job is still pending/running; the frame label's
 * status/energy just fill in as `children` (each image's own JobRow)
 * updates on its own poll. */
export function ScanFrameViewer({ job, subJobs }: { job: JobRow; subJobs: JobRow[] }) {
  const [frames, setFrames] = useState<ReturnType<typeof parseMultiFrameXyz> | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [showCoords, setShowCoords] = useState(false);

  const pathXyzKey = typeof job.artifacts?.path_xyz === "string" ? job.artifacts.path_xyz : null;
  useEffect(() => {
    if (!pathXyzKey) return;
    let cancelled = false;
    fetch(jobArtifactUrl(job.job_id, "path_xyz"))
      .then((r) => r.text())
      .then((text) => {
        if (!cancelled) setFrames(parseMultiFrameXyz(text));
      });
    return () => {
      cancelled = true;
    };
  }, [job.job_id, pathXyzKey]);

  if (!frames || frames.length === 0) {
    return <div className="text-xs text-text-muted">Loading scan path...</div>;
  }

  const clamped = Math.min(frameIndex, frames.length - 1);
  const frame = frames[clamped];
  const childRow = subJobs[clamped] as JobRow | undefined;
  const energies = (job.summary?.["energies_hartree"] as (number | null)[] | undefined) ?? [];
  const energy = energies[clamped];

  let statusLabel: string = childRow ? childRow.status : "pending";
  if (energy != null) statusLabel = `completed, energy ${energy.toFixed(6)} Eh`;
  else if (childRow?.status === "failed") statusLabel = "failed";

  return (
    <div className="flex flex-col gap-2">
      <MoleculeViewer molecule={frame} height={280} />
      <label className="flex items-center gap-2 text-[10.5px] text-text-muted">
        Frame
        <input
          type="range"
          min={0}
          max={frames.length - 1}
          step={1}
          value={clamped}
          onChange={(e) => setFrameIndex(Number(e.target.value))}
          className="flex-1"
        />
        <span className="w-10 font-mono text-text">
          {clamped + 1}/{frames.length}
        </span>
      </label>
      <div className="text-[10.5px] text-text-muted">{statusLabel}</div>
      <button
        onClick={() => setShowCoords((s) => !s)}
        className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
      >
        {showCoords ? "Hide" : "Show"} coordinates
      </button>
      {showCoords && (
        <div className="flex flex-col gap-1">
          <div className="text-[10.5px] text-text-muted">
            All {frames.length} frames, in path order (xmol multi-frame format):
          </div>
          <pre className="max-h-48 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] text-text-muted">
            {frames.map((f) => moleculeToXyzBlock(f)).join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}
