import { useEffect, useRef } from "react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import type { MoleculeDict } from "../lib/api";

interface Atom {
  elem: string;
  x: number;
  y: number;
  z: number;
}

function buildXyzBlock(atoms: Atom[]): string {
  const lines = [String(atoms.length), "molecule"];
  for (const a of atoms) lines.push(`${a.elem} ${a.x.toFixed(8)} ${a.y.toFixed(8)} ${a.z.toFixed(8)}`);
  return lines.join("\n");
}

/** Read-only imperative 3Dmol viewer -- rebuilds only when the molecule
 * data itself changes (content-hash guard, not reference identity), since
 * viewer instance/model state lives outside React's render tree. */
export function MoleculeViewer({ molecule, height = 288 }: { molecule: MoleculeDict | null; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const firstRenderRef = useRef(true);
  const lastKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    viewerRef.current = $3Dmol.createViewer(containerRef.current, { backgroundColor: "0x14161a" });
    return () => {
      viewerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const key = molecule ? JSON.stringify({ symbols: molecule.symbols, coords: molecule.coords }) : null;
    if (key === lastKeyRef.current) return;
    lastKeyRef.current = key;

    const v = viewerRef.current;
    if (!v) return;
    v.removeAllModels();
    v.removeAllLabels();
    const atoms: Atom[] = molecule
      ? molecule.symbols.map((elem, i) => ({
          elem,
          x: molecule.coords[i][0],
          y: molecule.coords[i][1],
          z: molecule.coords[i][2],
        }))
      : [];
    if (atoms.length > 0) {
      v.addModel(buildXyzBlock(atoms), "xyz");
      v.setStyle({}, { stick: {}, sphere: { scale: 0.25 } });
      atoms.forEach((a, i) => {
        v.addLabel(String(i + 1), {
          position: { x: a.x, y: a.y, z: a.z },
          backgroundColor: "black",
          backgroundOpacity: 0.55,
          fontColor: "white",
          fontSize: 11,
          borderThickness: 0,
          inFront: true,
          showBackground: true,
        });
      });
      if (firstRenderRef.current) {
        v.zoomTo();
        firstRenderRef.current = false;
      }
    }
    v.render();
  }, [molecule]);

  return <div ref={containerRef} style={{ height }} className="mol-bezel rounded border border-border" />;
}
