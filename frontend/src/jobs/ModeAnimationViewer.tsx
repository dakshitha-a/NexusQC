import { useEffect, useRef } from "react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import type { MoleculeDict } from "../lib/api";

interface Props {
  molecule: MoleculeDict;
  /** normal_modes[selectedMode]: per-atom [dx,dy,dz] Cartesian displacement
   * vector, same 1-based atom ordering as `molecule`/the main viewer. */
  displacement: number[][];
  /** Pixel height of the viewer box (default 224, i.e. Tailwind's h-56) --
   * lets a caller (e.g. ExpandablePanel) grow the viewer when expanded. */
  height?: number;
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

export function ModeAnimationViewer({ molecule, displacement, height = 224 }: Props) {
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
    v.clear(); // also wipes labels -- must re-add below
    const xyz = toVibrateXyz(molecule, displacement);
    const model = v.addModel(xyz, "xyz");
    model.vibrate(10, 1.2, true);
    v.setStyle({}, { stick: { radius: 0.1 }, sphere: { scale: 0.25 } });
    // Atom numbers at equilibrium position, same 1-based convention as
    // MoleculeViewer -- static labels don't track vibrate()'s per-frame
    // displacement, which is expected: they mark which atom is which, not
    // its instantaneous position mid-oscillation.
    molecule.symbols.forEach((_sym, i) => {
      const [x, y, z] = molecule.coords[i];
      v.addLabel(String(i + 1), {
        position: { x, y, z },
        backgroundColor: "black",
        backgroundOpacity: 0.55,
        fontColor: "white",
        fontSize: 11,
        borderThickness: 0,
        inFront: true,
        showBackground: true,
      });
    });
    v.zoomTo();
    v.animate({ loop: "backAndForth", reps: 0 });
    v.render();
    return () => {
      v.stopAnimate();
    };
  }, [molecule, displacement]);

  // Same reasoning as MoleculeViewer's own resize effect: 3Dmol doesn't
  // observe container size changes on its own, so a height prop change
  // (ExpandablePanel growing this panel) needs an explicit resize() +
  // zoomTo() to actually fill the bigger box, not just resize the canvas
  // underneath an unchanged view.
  useEffect(() => {
    const v = viewerRef.current;
    if (!v) return;
    v.resize();
    v.zoomTo();
    v.render();
  }, [height]);

  // `relative` is load-bearing, not decorative: 3Dmol positions its canvas
  // absolutely and tries to set the container to position:relative itself,
  // but its check (createViewer's `viewerdiv.style.position == 'static'`)
  // reads the inline style attribute, which a CSS-class-applied position
  // never populates -- so without this class, the canvas escapes to the
  // nearest *actually* positioned ancestor (this drawer's `fixed` root),
  // rendering the molecule floating over the dialog header instead of
  // inside this box. Confirmed via Playwright screenshot before this fix.
  return <div ref={containerRef} className="relative rounded border border-border" style={{ height }} />;
}
