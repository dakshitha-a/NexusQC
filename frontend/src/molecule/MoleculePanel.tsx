import { Suspense, lazy, useEffect, useState } from "react";
import { Maximize2, Paperclip, PenTool, RotateCcw, Trash2 } from "lucide-react";
import { useChatStore } from "../lib/chatStore";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { useAttachedFrameStore } from "../lib/attachedFrameStore";
import { MoleculeViewer } from "./MoleculeViewer";
import { Flyout } from "../app-shell/Flyout";
import { moleculeToXyzBlock } from "./xyz";
import * as api from "../lib/api";
import type { MoleculeDict, ThreadState } from "../lib/api";

// ketcher-react pulls in an indigo wasm build (multi-MB) -- lazy-loaded so
// the main app bundle/startup is never affected by a feature most page
// loads never touch, and split off from MoleculePanel's own default
// export so an unrelated MoleculePanel change doesn't need this heavy
// chunk re-evaluated in dev.
const MoleculeBuilderModal = lazy(() =>
  import("./MoleculeBuilderModal").then((m) => ({ default: m.MoleculeBuilderModal })),
);

// F-014: `fallback={null}` meant clicking "Build a molecule" produced
// literally nothing on screen for a measured 3,484ms while the 28.7MB
// Ketcher chunk downloaded and evaluated -- no modal, no spinner, no
// disabled button. The only available reading of that is "the click didn't
// register", so the natural response is to click again.
//
// This is a full-screen overlay rather than an inline spinner because the
// modal it stands in for is itself full-screen: showing the sketcher's own
// frame arriving in place, rather than a small indicator somewhere else on
// the page that then vanishes as an unrelated-looking dialog appears.
function BuilderLoading() {
  return (
    <div
      data-testid="molecule-builder-loading"
      className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-black/50"
    >
      <div className="flex w-72 flex-col gap-2 rounded-lg border border-border bg-surface p-4 shadow-2xl">
        <div className="text-sm font-medium text-text">Loading the 2D sketcher…</div>
        <div className="text-[11px] text-text-muted">
          First open only — the editor is a large download and is cached afterwards.
        </div>
        <div className="skeleton-shimmer mt-1 h-1.5 w-full rounded" />
      </div>
    </div>
  );
}

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
  const [builderOpen, setBuilderOpen] = useState(false);

  const handleBuilt = (state: ThreadState) => {
    setMolecule(state.molecule);
    setMoleculeFrames(state.molecule_frames);
  };

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
      <div className="mol-bezel flex h-72 flex-col items-center justify-center gap-2 rounded border border-border bg-surface text-xs text-text-muted">
        No molecule set yet.
        {activeThreadId && (
          <button
            onClick={() => setBuilderOpen(true)}
            title="Build a molecule (2D sketcher)"
            className="flex items-center gap-1.5 rounded border border-border px-2.5 py-1 text-text-muted hover:bg-surface-raised hover:text-text"
          >
            <PenTool size={12} /> Build a molecule
          </button>
        )}
        {builderOpen && activeThreadId && (
          <Suspense fallback={<BuilderLoading />}>
            <MoleculeBuilderModal threadId={activeThreadId} onClose={() => setBuilderOpen(false)} onBuilt={handleBuilt} />
          </Suspense>
        )}
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
            onClick={() => setBuilderOpen(true)}
            className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Build a molecule (2D sketcher)"
          >
            <PenTool size={13} />
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
      {builderOpen && activeThreadId && (
        <Suspense fallback={<BuilderLoading />}>
          <MoleculeBuilderModal threadId={activeThreadId} onClose={() => setBuilderOpen(false)} onBuilt={handleBuilt} />
        </Suspense>
      )}
    </div>
  );
}
