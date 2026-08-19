import { useEffect, useState } from "react";
import { Paperclip, Loader2 } from "lucide-react";
import { jobArtifactUrl, tagJobFrame } from "../lib/api";
import type { JobRow } from "../lib/api";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { useChatStore } from "../lib/chatStore";
import { MoleculeViewer } from "../molecule/MoleculeViewer";
import { moleculeToXyzBlock, parseMultiFrameXyz } from "../molecule/xyz";
import { FrameStepper } from "./FrameStepper";

/** Cycling geometry viewer for a `geometry_set` job -- reads its own
 * path_xyz artifact (written once at creation, see JobManager.
 * submit_geometry_set) and parses it with the SAME frontend xyz.ts parser
 * ScanFrameViewer already uses for a pes_scan master; no dedicated frames
 * endpoint. Adds a per-frame "tag" action (Phase 3's "tag frame N into a
 * draft"): POSTs to tag_job_frame, which attaches that one geometry as the
 * active molecule the same way the molecule panel's own frame-attach does
 * -- start_job_draft/set_geometry then pick it up unchanged. */
export function GeometrySetViewer({
  job,
  threadId,
  height = 280,
}: {
  job: JobRow;
  /** The thread to tag a frame INTO. Falls back to whichever thread is
   * currently active (the Job Manager panel's global drawer doesn't
   * receive its own threadId) -- tagging is disabled entirely if neither
   * is available. */
  threadId?: string;
  height?: number;
}) {
  const [frames, setFrames] = useState<ReturnType<typeof parseMultiFrameXyz> | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [showCoords, setShowCoords] = useState(false);
  const [tagState, setTagState] = useState<"idle" | "pending" | "error">("idle");
  const [tagError, setTagError] = useState<string | null>(null);
  const activeThreadId = useActiveThreadStore((s) => s.activeThreadId);
  const setMolecule = useChatStore((s) => s.setMolecule);
  const setMoleculeFrames = useChatStore((s) => s.setMoleculeFrames);
  const effectiveThreadId = threadId ?? activeThreadId ?? null;

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
    return <div className="text-xs text-text-muted">Loading geometry set...</div>;
  }

  const clamped = Math.min(frameIndex, frames.length - 1);
  const frame = frames[clamped];

  const handleTag = async () => {
    if (!effectiveThreadId) return;
    setTagState("pending");
    setTagError(null);
    try {
      // tag_job_frame is 1-based (this app's atom-numbering convention for
      // anything a user sees) -- the frame slider below is 0-indexed, so
      // the +1 conversion happens right here, at the boundary.
      const { state } = await tagJobFrame(effectiveThreadId, job.job_id, clamped + 1);
      setMolecule(state.molecule);
      setMoleculeFrames(state.molecule_frames);
      setTagState("idle");
    } catch (err) {
      setTagState("error");
      setTagError(String(err));
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <MoleculeViewer molecule={frame} height={height} />
      <div className="flex items-center gap-2">
        <FrameStepper index={clamped} count={frames.length} onChange={setFrameIndex} noun="Geometry" />
        <button
          onClick={handleTag}
          disabled={!effectiveThreadId || tagState === "pending"}
          className="flex shrink-0 items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[11px] text-text-muted hover:border-accent hover:text-accent disabled:opacity-40"
          title={
            effectiveThreadId
              ? `Tag geometry ${clamped + 1} as the active molecule`
              : "Open a conversation first"
          }
          data-testid="geometry-set-tag-frame"
        >
          {tagState === "pending" ? <Loader2 size={11} className="animate-spin" /> : <Paperclip size={11} />}
          Tag this geometry
        </button>
      </div>
      {tagState === "error" && <div className="text-[10.5px] text-status-failed">{tagError}</div>}
      <button
        onClick={() => setShowCoords((s) => !s)}
        className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
      >
        {showCoords ? "Hide" : "Show"} coordinates
      </button>
      {showCoords && (
        <div className="flex flex-col gap-1">
          <div className="text-[10.5px] text-text-muted">
            All {frames.length} geometries, in upload order (xmol multi-frame format):
          </div>
          <pre className="max-h-48 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] text-text-muted">
            {frames.map((f) => moleculeToXyzBlock(f)).join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}
