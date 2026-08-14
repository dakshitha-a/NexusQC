import { useEffect, useState } from "react";
import { Maximize2, Paperclip, RotateCcw, Trash2 } from "lucide-react";
import { useChatStore } from "../lib/chatStore";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { useAttachedFrameStore } from "../lib/attachedFrameStore";
import { MoleculeViewer } from "./MoleculeViewer";
import { Flyout } from "../app-shell/Flyout";
import { moleculeToXyzBlock } from "./xyz";
import * as api from "../lib/api";
import type { MoleculeDict } from "../lib/api";

function CoordsToggle({ molecule }: { molecule: MoleculeDict }) {
  const [showCoords, setShowCoords] = useState(false);
  return (
    <>
      <button
        onClick={() => setShowCoords((s) => !s)}
        className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
      >
        {showCoords ? "Hide" : "Show"} coordinates
      </button>
      {/* molecule is whichever frame the slider currently has selected, so
          this re-renders with the new frame's coordinates automatically as
          the slider moves -- no extra wiring needed beyond passing the
          right prop down. */}
      {showCoords && (
        <pre className="max-h-40 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] text-text-muted">
          {moleculeToXyzBlock(molecule)}
        </pre>
      )}
    </>
  );
}

export function MoleculePanel() {
  const frames = useChatStore((s) => s.moleculeFrames);
  const setMolecule = useChatStore((s) => s.setMolecule);
  const setMoleculeFrames = useChatStore((s) => s.setMoleculeFrames);
  const activeThreadId = useActiveThreadStore((s) => s.activeThreadId);
  const { attachedFrame, setAttachedFrame, clearAttachedFrame } = useAttachedFrameStore();
  const [expanded, setExpanded] = useState(false);
  const [frameIndex, setFrameIndex] = useState(0);

  // Jump to the newest frame whenever the frame count changes (a new
  // molecule was just set, or a frame was deleted) -- keeps the slider
  // showing something meaningful instead of stranding it on a stale index.
  const frameCount = frames.length;
  useEffect(() => {
    if (frameCount > 0) setFrameIndex(frameCount - 1);
  }, [frameCount]);

  const clamped = frames.length > 0 ? Math.min(frameIndex, frames.length - 1) : 0;
  const frame = frames[clamped];

  const handleReset = async () => {
    if (!activeThreadId) return;
    setMolecule(null);
    setMoleculeFrames([]);
    clearAttachedFrame();
    setExpanded(false);
    try {
      await api.resetMolecule(activeThreadId);
    } catch {
      /* the panel already reflects the clear locally; a stale backend
         write here isn't worth surfacing as an error for a reset button */
    }
  };

  const handleDeleteFrame = async (frameId: string) => {
    if (!activeThreadId) return;
    if (attachedFrame?.frame_id === frameId) clearAttachedFrame();
    setMoleculeFrames(frames.filter((f) => f.id !== frameId));
    try {
      await api.deleteMoleculeFrame(activeThreadId, frameId);
    } catch {
      /* the panel already reflects the delete locally; a stale backend
         write here isn't worth surfacing as an error for a delete button */
    }
  };

  const handleAttach = () => {
    if (!frame) return;
    setAttachedFrame({ frame_id: frame.id, label: `#${clamped + 1} ${frame.description}` });
  };

  if (!frame) {
    return (
      <div className="mol-bezel flex h-72 items-center justify-center rounded border border-border bg-surface text-xs text-text-muted">
        No molecule set yet.
      </div>
    );
  }

  const molecule = frame.molecule;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs text-text-muted">
          <span className="text-text">{molecule.name ?? molecule.smiles}</span>
          {" · "}
          {molecule.smiles} · charge {molecule.charge ?? 0}, mult {molecule.multiplicity ?? 1} ·{" "}
          {molecule.symbols.length} atoms
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={handleAttach}
            className={`rounded p-1 hover:bg-surface-raised hover:text-text ${
              attachedFrame?.frame_id === frame.id ? "text-accent" : "text-text-muted"
            }`}
            title="Attach this frame to prompt"
          >
            <Paperclip size={13} />
          </button>
          <button
            onClick={() => handleDeleteFrame(frame.id)}
            className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Delete this frame"
          >
            <Trash2 size={13} />
          </button>
          <button
            onClick={() => setExpanded(true)}
            className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Enlarge"
          >
            <Maximize2 size={13} />
          </button>
          <button
            onClick={handleReset}
            className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Reset (clear all frames and geometry)"
          >
            <RotateCcw size={13} />
          </button>
        </div>
      </div>
      {frames.length > 1 && (
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={0}
            max={frames.length - 1}
            step={1}
            value={clamped}
            onChange={(e) => setFrameIndex(Number(e.target.value))}
            className="flex-1"
          />
          <span className="shrink-0 text-[11px] text-text-muted">
            Frame {clamped + 1}/{frames.length}
          </span>
        </div>
      )}
      <div className="truncate text-[11px] italic text-text-muted" title={frame.description}>
        {frame.description}
        {attachedFrame?.frame_id === frame.id && <span className="text-accent"> · attached to next prompt</span>}
      </div>
      {/* Unmounted while the flyout is open rather than kept alongside it --
          each MoleculeViewer owns a live WebGL context, and this app has
          already hit the browser's per-page context cap once from stacking
          contexts that should have been mutually exclusive (see
          MoleculeViewer.tsx's docstring). */}
      {!expanded && <MoleculeViewer molecule={molecule} height={240} />}
      <CoordsToggle molecule={molecule} />
      {expanded && (
        <Flyout open onClose={() => setExpanded(false)} title={molecule.name ?? "Molecule"} widthClassName="w-160">
          <div className="flex h-full flex-col gap-2">
            <MoleculeViewer molecule={molecule} height={520} />
            <CoordsToggle molecule={molecule} />
          </div>
        </Flyout>
      )}
    </div>
  );
}
