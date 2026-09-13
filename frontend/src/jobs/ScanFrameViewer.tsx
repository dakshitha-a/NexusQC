import { useEffect, useState } from "react";
import { checkRawResponse, jobArtifactUrl } from "../lib/api";
import type { JobChildrenPage, JobRow } from "../lib/api";
import { MoleculeViewer } from "../molecule/MoleculeViewer";
import { jobFilenameStem } from "../lib/jobFilename";
import { moleculeToXyzBlock, parseMultiFrameXyz } from "../molecule/xyz";
import { FrameStepper } from "./FrameStepper";

/** Multi-frame geometry viewer for a pes_scan master job -- the path is
 * written to disk (artifacts.path_xyz) the instant the scan is approved
 * (see JobManager.submit_scan), so this renders immediately even while
 * every image's own sub-job is still pending/running; the frame label's
 * status/energy just fill in as `childrenPage` (a window of the scan's
 * own per-image JobRows, see P7.3) updates on its own poll.
 *
 * `childrenPage` only ever covers a window of the full path (offset..
 * offset+items.length) at masters with more images than fit in one page
 * -- scrubbing to a frame outside that window calls `onRequestOffset` so
 * the drawer re-points the shared window at the page containing it. The
 * geometry itself never waits on this: it comes from path_xyz, one file
 * covering every frame, loaded once below. */
export function ScanFrameViewer({
  job,
  childrenPage,
  onRequestOffset,
  height = 280,
  onDownloadError,
}: {
  job: JobRow;
  childrenPage: JobChildrenPage | undefined;
  onRequestOffset: (index: number) => void;
  /** Passed straight through to the inner MoleculeViewer -- lets a caller
   * (e.g. ExpandablePanel) grow the frame viewer when expanded. */
  height?: number;
  /** Also straight through. Without it a failed PNG capture reaches nothing
   * but console.error, so the button simply stops spinning and the user is
   * told nothing. */
  onDownloadError?: (message: string) => void;
}) {
  const [frames, setFrames] = useState<ReturnType<typeof parseMultiFrameXyz> | null>(null);
  // Set by the fetch below when the artifact cannot be read, so the
  // panel can say so instead of claiming to still be loading (R-068).
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [showCoords, setShowCoords] = useState(false);

  const pathXyzKey = typeof job.artifacts?.path_xyz === "string" ? job.artifacts.path_xyz : null;
  useEffect(() => {
    if (!pathXyzKey) return;
    let cancelled = false;
    // r.ok is checked and the promise has a .catch, which R-068 is about:
    // fetch does not reject on 4xx or 5xx, so an artifact that 404s (an
    // evicted job, a cleaned archive) resolved with an HTML error body,
    // parseMultiFrameXyz found no frames in it, and the panel rendered
    // "Loading scan path..." for ever with an unhandled rejection in the
    // console and no way to tell slow from broken. NebFrameViewer beside
    // these three already did it correctly, which is what made it a fix
    // rather than a design question.
    fetch(jobArtifactUrl(job.job_id, "path_xyz"))
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
  }, [job.job_id, pathXyzKey]);

  if (!frames || frames.length === 0) {
    return (
      <div className="text-xs text-text-muted">
        {fetchError ? `Couldn't load the scan path: ${fetchError}` : "Loading scan path..."}
      </div>
    );
  }

  const clamped = Math.min(frameIndex, frames.length - 1);
  const frame = frames[clamped];
  const inWindow = !!childrenPage && clamped >= childrenPage.offset && clamped < childrenPage.offset + childrenPage.items.length;
  const childRow = inWindow ? childrenPage!.items[clamped - childrenPage!.offset] : undefined;
  const energies = (job.summary?.["energies_hartree"] as (number | null)[] | undefined) ?? [];
  const energy = energies[clamped];

  const goToFrame = (next: number) => {
    setFrameIndex(next);
    if (!childrenPage || next < childrenPage.offset || next >= childrenPage.offset + childrenPage.items.length) {
      onRequestOffset(next);
    }
  };

  let statusLabel: string = childRow ? childRow.status : "pending";
  if (energy != null) statusLabel = `completed, energy ${energy.toFixed(6)} Eh`;
  else if (childRow?.status === "failed") statusLabel = "failed";

  return (
    <div className="flex flex-col gap-2">
      <MoleculeViewer
        molecule={frame}
        height={height}
        filenameBase={jobFilenameStem(job)}
        descriptor={`image${clamped + 1}_view`}
        onDownloadError={onDownloadError}
      />
      <FrameStepper
        index={clamped}
        count={frames.length}
        onChange={goToFrame}
        label={energy != null ? `${energy.toFixed(6)} Eh` : undefined}
      />
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
            All {frames.length} frames, in path order (xmol multi-frame format):
          </div>
          <pre className="max-h-48 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-2xs text-text-muted">
            {frames.map((f) => moleculeToXyzBlock(f)).join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}
