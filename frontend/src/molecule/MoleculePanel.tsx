import { useState } from "react";
import { useChatStore } from "../lib/chatStore";
import { MoleculeViewer } from "./MoleculeViewer";

export function MoleculePanel() {
  const molecule = useChatStore((s) => s.molecule);
  const [showCoords, setShowCoords] = useState(false);

  if (!molecule) {
    return (
      <div className="mol-bezel flex h-72 items-center justify-center rounded border border-border bg-surface text-xs text-text-muted">
        No molecule set yet.
      </div>
    );
  }

  const xyzBlock = [
    String(molecule.symbols.length),
    molecule.name ?? "molecule",
    ...molecule.symbols.map((el, i) => {
      const [x, y, z] = molecule.coords[i];
      return `${el} ${x.toFixed(8)} ${y.toFixed(8)} ${z.toFixed(8)}`;
    }),
  ].join("\n");

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-text-muted">
        <span className="text-text">{molecule.name ?? molecule.smiles}</span>
        {" · "}
        {molecule.smiles} · charge {molecule.charge ?? 0}, mult {molecule.multiplicity ?? 1} ·{" "}
        {molecule.symbols.length} atoms
      </div>
      <MoleculeViewer molecule={molecule} height={240} />
      <button
        onClick={() => setShowCoords((s) => !s)}
        className="self-start text-xs text-text-muted underline decoration-dotted hover:text-text"
      >
        {showCoords ? "Hide" : "Show"} coordinates
      </button>
      {showCoords && (
        <pre className="max-h-40 overflow-y-auto rounded border border-border bg-bg p-2 font-mono text-[11px] text-text-muted">
          {xyzBlock}
        </pre>
      )}
    </div>
  );
}
