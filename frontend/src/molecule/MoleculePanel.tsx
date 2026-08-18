import { Suspense, lazy, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Maximize2, Paperclip, PenTool, RotateCcw, Trash2 } from "lucide-react";
import { useChatStore } from "../lib/chatStore";
import { useActiveThreadStore } from "../lib/activeThreadStore";
import { useAttachedFrameStore } from "../lib/attachedFrameStore";
import { MoleculeViewer } from "./MoleculeViewer";
import { Flyout } from "../app-shell/Flyout";
import { FrameStepper } from "../jobs/FrameStepper";
import { molecularFormula, moleculeToXyzBlock } from "./xyz";
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
  // Deliberately NOT reset when the frame changes: someone who opened the
  // details wants to compare charge/multiplicity/SMILES across frames, and
  // having the panel snap shut on every step would defeat that. It is also
  // what keeps stepping height-stable in the open state as well as the closed
  // one -- the panel stays open, so nothing appears or disappears.
  const [detailsOpen, setDetailsOpen] = useState(false);

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
  // Name, else a Hill-notation formula. NOT the SMILES: past a few atoms it is
  // unreadable as a title and long enough to wrap, which is what made this
  // header change size frame to frame.
  const title = molecule.name ?? molecularFormula(molecule.symbols);
  const isAttached = attachedFrame?.frame_id === frame.id;
  // A frame's description is usually the identifier it was resolved from, so
  // for a named molecule it just repeats the title -- "uracil" above
  // "uracil". When it adds nothing, spend the line on the formula and atom
  // count instead, which no other always-visible line carries.
  const describesSomethingNew =
    frame.description && frame.description.trim().toLowerCase() !== title.trim().toLowerCase();
  const subtitle = describesSomethingNew
    ? frame.description
    : `${molecularFormula(molecule.symbols)} · ${molecule.symbols.length} atoms`;

  return (
    <div className="flex flex-col gap-2">
      {/* Identity block: exactly two lines, both fixed height, both truncated.
          It used to be one free-flowing line carrying name, SMILES, charge,
          multiplicity and atom count together, in a flex child with no
          `min-w-0` -- so a flex item's default `min-width: auto` let its
          intrinsic content width push the whole row wider, and the text
          wrapped to a second line when it could not. Scrubbing from water to
          uracil therefore changed BOTH the panel's width and its height on
          every frame step, shifting everything below it.

          Fixed height is the requirement here, not merely nice: this sits
          directly above the viewer and the frame controls, and a header that
          changes height as you step frames moves the control you are actively
          clicking. The details panel below can change height, because opening
          it is a deliberate act rather than a side effect of scrubbing. */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-4 items-center gap-1.5">
            <span className="truncate text-xs text-text" title={title}>
              {title}
            </span>
            {isAttached && (
              <span className="shrink-0 rounded bg-accent-muted px-1 text-[10px] text-accent">
                attached
              </span>
            )}
          </div>
          <button
            onClick={() => setDetailsOpen((v) => !v)}
            data-testid="molecule-details-toggle"
            title={detailsOpen ? "Hide details" : "Show charge, multiplicity, atom count and SMILES"}
            className="flex h-4 items-center gap-1 text-left text-[11px] text-text-muted hover:text-text"
          >
            {detailsOpen ? (
              <ChevronDown size={11} className="shrink-0" />
            ) : (
              <ChevronRight size={11} className="shrink-0" />
            )}
            <span className={`truncate ${describesSomethingNew ? "italic" : ""}`}>{subtitle}</span>
          </button>
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
      {/* Charge, multiplicity, atom count, then the SMILES -- in that order,
          longest last. The SMILES is the one field with no useful bound on its
          length, so it lives here rather than in the always-visible header,
          and it wraps freely (`break-all`) because a canonical SMILES has no
          spaces to break at. */}
      {detailsOpen && (
        <dl
          data-testid="molecule-details"
          className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded border border-border bg-bg/40 px-2 py-1.5 text-[11px]"
        >
          <dt className="text-text-muted">Charge</dt>
          <dd className="tabular-nums text-text">{molecule.charge ?? 0}</dd>
          <dt className="text-text-muted">Multiplicity</dt>
          <dd className="tabular-nums text-text">{molecule.multiplicity ?? 1}</dd>
          <dt className="text-text-muted">Atoms</dt>
          <dd className="tabular-nums text-text">{molecule.symbols.length}</dd>
          <dt className="text-text-muted">SMILES</dt>
          <dd className="min-w-0 break-all font-mono text-text">{molecule.smiles ?? "--"}</dd>
          {/* Last, and only when it says something the title does not: line 2
              truncates it, so this is where the full text is recoverable. */}
          {describesSomethingNew && (
            <>
              <dt className="text-text-muted">From</dt>
              <dd className="min-w-0 break-words text-text">{frame.description}</dd>
            </>
          )}
        </dl>
      )}
      <FrameStepper index={clamped} count={frames.length} onChange={setFrameIndex} />
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
