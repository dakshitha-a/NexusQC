import { useState } from "react";
import { Maximize2, RotateCcw } from "lucide-react";
import { useChatStore } from "../lib/chatStore";
import { useActiveThreadStore } from "../lib/activeThreadStore";
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
      {showCoords && (
        <pre className="max-h-40 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] text-text-muted">
          {moleculeToXyzBlock(molecule)}
        </pre>
      )}
    </>
  );
}

export function MoleculePanel() {
  const molecule = useChatStore((s) => s.molecule);
  const setMolecule = useChatStore((s) => s.setMolecule);
  const activeThreadId = useActiveThreadStore((s) => s.activeThreadId);
  const [expanded, setExpanded] = useState(false);

  const handleReset = async () => {
    if (!activeThreadId) return;
    setMolecule(null);
    setExpanded(false);
    try {
      await api.resetMolecule(activeThreadId);
    } catch {
      /* the panel already reflects the clear locally; a stale backend
         write here isn't worth surfacing as an error for a reset button */
    }
  };

  if (!molecule) {
    return (
      <div className="mol-bezel flex h-72 items-center justify-center rounded border border-border bg-surface text-xs text-text-muted">
        No molecule set yet.
      </div>
    );
  }

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
            onClick={() => setExpanded(true)}
            className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Enlarge"
          >
            <Maximize2 size={13} />
          </button>
          <button
            onClick={handleReset}
            className="rounded p-1 text-text-muted hover:bg-surface-raised hover:text-text"
            title="Reset (clear loaded geometry)"
          >
            <RotateCcw size={13} />
          </button>
        </div>
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
