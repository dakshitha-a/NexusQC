import { useEffect, useRef } from "react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import type { MoleculeDict } from "../lib/api";

interface Props {
  molecule: MoleculeDict;
  /** normal_modes[selectedMode]: per-atom [dx,dy,dz] Cartesian displacement
   * vector, same 1-based atom ordering as `molecule`/the main viewer. */
  displacement: number[][];
}

// Builds a 7-column XYZ block ("elem x y z dx dy dz") -- 3Dmol's XYZ parser
// (parsers/XYZ.ts) populates atom.dx/dy/dz from exactly this column layout
// when a line has >=7 tokens, which GLModel.vibrate() then reads to
// generate animation frames. No other public 3Dmol API accepts raw
// displacement vectors directly.
function toVibrateXyz(molecule: MoleculeDict, displacement: number[][]): string {
  const lines = [String(molecule.symbols.length), "vibration mode"];
  molecule.symbols.forEach((sym, i) => {
    const [x, y, z] = molecule.coords[i];
    const [dx, dy, dz] = displacement[i];
    lines.push(`${sym} ${x} ${y} ${z} ${dx} ${dy} ${dz}`);
  });
  return lines.join("\n");
}

export function ModeAnimationViewer({ molecule, displacement }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    // See MoleculeViewer.tsx/MoCubeViewer.tsx's detailed comment: clearing
    // the container at the START of the init effect (not just cleanup) is
    // what actually prevents an orphaned <canvas> (and a leaked WebGL
    // context) surviving React 18 Strict Mode's mount->cleanup->remount.
    containerRef.current.innerHTML = "";
    viewerRef.current = $3Dmol.createViewer(containerRef.current, { backgroundColor: "0x14161a" });
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      if (containerRef.current) containerRef.current.innerHTML = "";
      viewerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const v = viewerRef.current;
    if (!v) return;
    v.clear();
    const xyz = toVibrateXyz(molecule, displacement);
    const model = v.addModel(xyz, "xyz");
    model.vibrate(10, 1.2, true);
    v.setStyle({}, { stick: { radius: 0.1 }, sphere: { scale: 0.25 } });
    v.zoomTo();
    v.animate({ loop: "backAndForth", reps: 0 });
    v.render();
    return () => {
      v.stopAnimate();
    };
  }, [molecule, displacement]);

  // `relative` is load-bearing, not decorative: 3Dmol positions its canvas
  // absolutely and tries to set the container to position:relative itself,
  // but its check (createViewer's `viewerdiv.style.position == 'static'`)
  // reads the inline style attribute, which a CSS-class-applied position
  // never populates -- so without this class, the canvas escapes to the
  // nearest *actually* positioned ancestor (this drawer's `fixed` root),
  // rendering the molecule floating over the dialog header instead of
  // inside this box. Confirmed via Playwright screenshot before this fix.
  return <div ref={containerRef} className="relative h-56 rounded border border-border" />;
}
