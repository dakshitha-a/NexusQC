import { useEffect, useState } from "react";
import { checkRawResponse, jobArtifactUrl, nebLiveFramesUrl } from "../lib/api";
import type { JobRow } from "../lib/api";
import type { OrbitalRow } from "./OrbitalTable";
import { MoCubeViewer } from "./MoCubeViewer";
import { MoleculeViewer } from "../molecule/MoleculeViewer";
import { jobFilenameStem } from "../lib/jobFilename";
import { parseMultiFrameXyz } from "../molecule/xyz";
import { FrameStepper } from "./FrameStepper";

/** Frame-by-frame geometry + per-frame orbital viewer for a completed or
 * still-running neb_ts job. Two distinct data sources, chosen by job
 * status (see orca_runner.run_neb_ts's docstring for why these are
 * different files, not the same file at different times):
 *  - completed: artifacts.neb_frames -- a combined xyz this app itself
 *    built (TS structure first, then the converged path in ORCA's own
 *    numbered order).
 *  - running: GET .../neb_frames_live -- the current iteration's images,
 *    read live from ORCA's own growing input_MEP_ALL_trj.xyz, polled
 *    every few seconds while the job runs.
 * Frame labels/gbw mapping differ between the two modes accordingly. */
export function NebFrameViewer({
  job,
  height = 280,
  onDownloadError,
}: {
  job: JobRow;
  /** Passed straight through to the inner MoleculeViewer -- lets a caller
   * (e.g. ExpandablePanel) grow the frame viewer when expanded. */
  height?: number;
  /** Also straight through. Without it a failed PNG capture reaches nothing
   * but console.error. */
  onDownloadError?: (message: string) => void;
}) {
  const isRunning = job.status === "running";
  const hasFinalFrames = typeof job.artifacts?.neb_frames === "string";

  const [frames, setFrames] = useState<ReturnType<typeof parseMultiFrameXyz> | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    if (hasFinalFrames) {
      let cancelled = false;
      fetch(jobArtifactUrl(job.job_id, "neb_frames"))
        .then((r) => checkRawResponse(r, "Couldn't load the NEB frames"))
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
    }
    if (isRunning) {
      let cancelled = false;
      const poll = () =>
        fetch(nebLiveFramesUrl(job.job_id))
          .then((r) => checkRawResponse(r, "Couldn't load the live NEB frames"))
          .then((r) => r.text())
          .then((text) => {
            if (!cancelled && text.trim()) setFrames(parseMultiFrameXyz(text));
          })
          .catch((e) => {
            // A single failed poll tick isn't worth surfacing (the next
            // tick usually succeeds) -- only shown if frames never loaded
            // at all (see the !frames render branch below).
            if (!cancelled) setFetchError(String(e));
          });
      poll();
      const interval = setInterval(poll, 3000);
      return () => {
        cancelled = true;
        clearInterval(interval);
      };
    }
  }, [job.job_id, hasFinalFrames, isRunning]);

  const orbitalTable = job.summary?.["orbital_table"] as OrbitalRow[] | undefined;
  const defaultOrbital =
    orbitalTable && orbitalTable.length > 0
      ? Math.max(...orbitalTable.filter((r) => r.occupancy > 0).map((r) => r.index), 1)
      : 1;
  const [orbitalIndex, setOrbitalIndex] = useState<number | null>(null);
  const effectiveOrbitalIndex = orbitalIndex ?? defaultOrbital;
  const [showOrbital, setShowOrbital] = useState(false);

  if (!frames || frames.length === 0) {
    return (
      <div className="text-xs text-text-muted">
        {fetchError
          ? `Couldn't load frames: ${fetchError}`
          : isRunning
            ? "Waiting for the first NEB iteration to finish..."
            : "Loading path..."}
      </div>
    );
  }

  const clamped = Math.min(frameIndex, frames.length - 1);
  const frame = frames[clamped];

  // Frame labeling + per-frame gbw mapping, per orca_runner.run_neb_ts's
  // artifact layout: completed frames are [TS, image0, image1, ...];
  // running (live) frames are just the current iteration's [image0,
  // image1, ...] with no TS frame yet.
  let label: string;
  let gbwFilename: string;
  if (hasFinalFrames) {
    if (clamped === 0) {
      label = "TS (refined)";
      gbwFilename = "input.gbw";
    } else {
      label = `Image ${clamped - 1}`;
      gbwFilename = `input_im${clamped - 1}.gbw`;
    }
  } else {
    label = `Image ${clamped} (current iteration)`;
    gbwFilename = `input_im${clamped}.gbw`;
  }

  return (
    <div className="flex flex-col gap-2">
      <MoleculeViewer
        molecule={frame}
        height={height}
        filenameBase={jobFilenameStem(job)}
        descriptor={`image${clamped + 1}_view`}
        onDownloadError={onDownloadError}
      />
      <FrameStepper index={clamped} count={frames.length} onChange={setFrameIndex} label={label} />
      {!hasFinalFrames && (
        <div className="text-3xs text-text-muted">
          Live view -- geometries update as ORCA writes each NEB iteration.
        </div>
      )}
      <button
        onClick={() => setShowOrbital((s) => !s)}
        className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
      >
        {showOrbital ? "Hide" : "Show"} orbital for this frame
      </button>
      {showOrbital && (
        <div className="flex flex-col gap-2 rounded border border-border p-2">
          <label className="flex items-center gap-2 text-3xs text-text-muted">
            Orbital #
            <input
              type="number"
              min={1}
              value={effectiveOrbitalIndex}
              onChange={(e) => setOrbitalIndex(Number(e.target.value))}
              className="w-16 rounded border border-border bg-surface px-1 py-0.5 text-xs text-text focus:border-accent"
            />
          </label>
          <MoCubeViewer
            key={`${clamped}-${gbwFilename}`}
            jobId={job.job_id}
            cubeLabels={[]}
            orbitalSelection={{ index: effectiveOrbitalIndex, spin: null, gbw: gbwFilename }}
          />
        </div>
      )}
    </div>
  );
}
