import { useEffect, useState } from "react";
import { jobArtifactUrl } from "../lib/api";
import type { JobRow } from "../lib/api";
import { MoleculeViewer } from "../molecule/MoleculeViewer";
import { moleculeToXyzBlock, parseMultiFrameXyz } from "../molecule/xyz";
import { FrameStepper } from "./FrameStepper";

/** Multi-frame geometry viewer for a wigner_ensemble master job -- closely
 * mirrors ScanFrameViewer, reading artifacts.ensemble_xyz (written for
 * every sample up front by JobManager.submit_ensemble, so this renders
 * immediately even while most samples are still pending/running) instead
 * of path_xyz. Unlike a pes_scan path, ensemble samples are i.i.d. draws
 * around an equilibrium geometry, not an ordered coordinate -- so there's
 * no "coordinate value"/energy-vs-position framing here, just "sample N
 * of M" plus that sample's own sub-job status. */
export function EnsembleFrameViewer({
  job,
  subJobs,
  height = 280,
}: {
  job: JobRow;
  subJobs: JobRow[];
  height?: number;
}) {
  const [frames, setFrames] = useState<ReturnType<typeof parseMultiFrameXyz> | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [showCoords, setShowCoords] = useState(false);

  const ensembleXyzKey = typeof job.artifacts?.ensemble_xyz === "string" ? job.artifacts.ensemble_xyz : null;
  useEffect(() => {
    if (!ensembleXyzKey) return;
    let cancelled = false;
    fetch(jobArtifactUrl(job.job_id, "ensemble_xyz"))
      .then((r) => r.text())
      .then((text) => {
        if (!cancelled) setFrames(parseMultiFrameXyz(text));
      });
    return () => {
      cancelled = true;
    };
  }, [job.job_id, ensembleXyzKey]);

  if (!frames || frames.length === 0) {
    return <div className="text-xs text-text-muted">Loading sampled geometries...</div>;
  }

  const clamped = Math.min(frameIndex, frames.length - 1);
  const frame = frames[clamped];
  const childRow = subJobs[clamped] as JobRow | undefined;
  const statusLabel = childRow ? childRow.status : "not yet dispatched";

  return (
    <div className="flex flex-col gap-2">
      <MoleculeViewer molecule={frame} height={height} />
      <FrameStepper index={clamped} count={frames.length} onChange={setFrameIndex} noun="Sample" />
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
            All {frames.length} sampled geometries (xmol multi-frame format):
          </div>
          <pre className="max-h-48 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] text-text-muted">
            {frames.map((f) => moleculeToXyzBlock(f)).join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}
