import { useEffect, useState } from "react";
import { checkRawResponse, jobArtifactUrl } from "../lib/api";
import type { JobChildrenPage, JobRow } from "../lib/api";
import { MoleculeViewer } from "../molecule/MoleculeViewer";
import { jobFilenameStem } from "../lib/jobFilename";
import { moleculeToXyzBlock, parseMultiFrameXyz } from "../molecule/xyz";
import { FrameStepper } from "./FrameStepper";

/** Multi-frame geometry viewer for a wigner_ensemble master job -- closely
 * mirrors ScanFrameViewer, reading artifacts.ensemble_xyz (written for
 * every sample up front by JobManager.submit_ensemble, so this renders
 * immediately even while most samples are still pending/running) instead
 * of path_xyz. Unlike a pes_scan path, ensemble samples are i.i.d. draws
 * around an equilibrium geometry, not an ordered coordinate -- so there's
 * no "coordinate value"/energy-vs-position framing here, just "sample N
 * of M" plus that sample's own sub-job status.
 *
 * `childrenPage` is a window of the ensemble's own per-sample JobRows
 * (P7.3) -- scrubbing outside it calls `onRequestOffset` so the drawer
 * re-points the shared window; the geometry itself comes from
 * ensemble_xyz (one file, every sample) and never waits on this. */
export function EnsembleFrameViewer({
  job,
  childrenPage,
  onRequestOffset,
  height = 280,
  onDownloadError,
}: {
  job: JobRow;
  childrenPage: JobChildrenPage | undefined;
  onRequestOffset: (index: number) => void;
  height?: number;
  /** Straight through to the inner MoleculeViewer. Without it a failed PNG
   * capture reaches nothing but console.error. */
  onDownloadError?: (message: string) => void;
}) {
  const [frames, setFrames] = useState<ReturnType<typeof parseMultiFrameXyz> | null>(null);
  // Set by the fetch below when the artifact cannot be read, so the
  // panel can say so instead of claiming to still be loading (R-068).
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [showCoords, setShowCoords] = useState(false);

  const ensembleXyzKey = typeof job.artifacts?.ensemble_xyz === "string" ? job.artifacts.ensemble_xyz : null;
  useEffect(() => {
    if (!ensembleXyzKey) return;
    let cancelled = false;
    // r.ok is checked and the promise has a .catch, which R-068 is about:
    // fetch does not reject on 4xx or 5xx, so an artifact that 404s (an
    // evicted job, a cleaned archive) resolved with an HTML error body,
    // parseMultiFrameXyz found no frames in it, and the panel rendered
    // "Loading sampled geometries..." for ever with an unhandled rejection in the
    // console and no way to tell slow from broken. NebFrameViewer beside
    // these three already did it correctly, which is what made it a fix
    // rather than a design question.
    fetch(jobArtifactUrl(job.job_id, "ensemble_xyz"))
      .then((r) => checkRawResponse(r, "Couldn't load the geometries"))
      .then((r) => r.text())
      .then((text) => {
        if (!cancelled) setFrames(parseMultiFrameXyz(text));
      })
      .catch((e) => {
        if (!cancelled) setFetchError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [job.job_id, ensembleXyzKey]);

  if (!frames || frames.length === 0) {
    return (
      <div className="text-xs text-text-muted">
        {fetchError ? `Couldn't load the sampled geometries: ${fetchError}` : "Loading sampled geometries..."}
      </div>
    );
  }

  const clamped = Math.min(frameIndex, frames.length - 1);
  const frame = frames[clamped];
  const inWindow = !!childrenPage && clamped >= childrenPage.offset && clamped < childrenPage.offset + childrenPage.items.length;
  const childRow = inWindow ? childrenPage!.items[clamped - childrenPage!.offset] : undefined;
  const statusLabel = childRow ? childRow.status : "not yet dispatched";

  const goToFrame = (next: number) => {
    setFrameIndex(next);
    if (!childrenPage || next < childrenPage.offset || next >= childrenPage.offset + childrenPage.items.length) {
      onRequestOffset(next);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <MoleculeViewer
        molecule={frame}
        height={height}
        filenameBase={jobFilenameStem(job)}
        descriptor={`sample${clamped + 1}_view`}
        onDownloadError={onDownloadError}
      />
      <FrameStepper index={clamped} count={frames.length} onChange={goToFrame} noun="Sample" />
      <div className="text-3xs text-text-muted">{statusLabel}</div>
      <button
        onClick={() => setShowCoords((s) => !s)}
        className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
      >
        {showCoords ? "Hide" : "Show"} coordinates
      </button>
      {showCoords && (
        <div className="flex flex-col gap-1">
          <div className="text-3xs text-text-muted">
            All {frames.length} sampled geometries (xmol multi-frame format):
          </div>
          <pre className="max-h-48 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-2xs text-text-muted">
            {frames.map((f) => moleculeToXyzBlock(f)).join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}
