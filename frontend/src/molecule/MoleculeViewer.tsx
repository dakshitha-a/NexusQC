import { useEffect, useRef } from "react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import type { MoleculeDict } from "../lib/api";
import { DownloadButton } from "../app-shell/DownloadButton";
import { downloadDataUri } from "../lib/download";
import { capturePng } from "./captureViewer";

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
export function MoleculeViewer({
  molecule,
  height = 288,
  filenameBase,
  onDownloadError,
}: {
  molecule: MoleculeDict | null;
  height?: number;
  // Caller-supplied stem for a captured PNG, so a download lands as
  // "20260817_water_Opt_B3LYP_def2-SVP_ORCA_78a32a61_view.png" rather than
  // just "water_view.png". Optional: this component is also used outside any
  // job context (the molecule panel), where the molecule's own name is the
  // best available answer.
  filenameBase?: string;
  onDownloadError?: (message: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const lastKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    // Clear the container before creating a viewer, not just on cleanup:
    // confirmed empirically that during React 18 Strict Mode's deliberate
    // mount->cleanup->remount dance on initial mount, containerRef.current
    // is already null by the time this effect's cleanup runs (Strict Mode
    // detaches the ref before invoking cleanup), even though the container
    // DOM node itself is NOT torn down across that cycle -- so a
    // cleanup-only clear silently does nothing, and the first mount's
    // <canvas> (with its own WebGL context) is still sitting in the
    // container when the second mount's createViewer() appends another
    // one on top of it. Clearing here, unconditionally, before creating a
    // new viewer, is what actually prevents the leak (verified: canvas
    // count stays at exactly 1 after this change, was 2 before it, purely
    // from Strict Mode's dev-mode double-invoke on a single real mount).
    // GLViewer has no destroy()/dispose() method, so this is also the
    // only way to release the *previous* viewer's WebGL context on a
    // genuine unmount+remount (switching to a conversation with a
    // different molecule, collapsing this panel) -- browsers cap the
    // number of live WebGL contexts per page (commonly 8-16); once
    // exhausted, every new context silently fails to initialize and the
    // viewer renders as a blank square from then on, which is the
    // originally reported bug this fixes.
    containerRef.current.innerHTML = "";
    viewerRef.current = $3Dmol.createViewer(containerRef.current, { backgroundColor: "0x14161a" });
    // lastKeyRef is a ref on this same component instance, so it survives
    // this remount untouched -- without resetting it here, React 18 Strict
    // Mode's dev-mode double-invoke (mount->cleanup->remount, see the
    // comment above) means Effect 2 already ran once against the *first*
    // (now-destroyed) viewer and recorded a key. Its second run, against
    // this brand new viewer, would then see an unchanged key, bail out
    // early, and leave this surviving viewer permanently empty -- a
    // genuinely blank preview with no error, matching the reported "often
    // fails to show a molecule" bug. Forcing the guard to treat any fresh
    // viewer as needing a rebuild fixes that regardless of whether the
    // molecule prop actually changed.
    lastKeyRef.current = null;
    return () => {
      if (containerRef.current) containerRef.current.innerHTML = "";
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
      // Unconditional, not gated to the first render: fires on every real
      // model rebuild (i.e. whenever the content-hash key above actually
      // changed) so a molecule swapped in later -- e.g. a geometry
      // optimization's final coordinates replacing the input structure --
      // is properly framed instead of inheriting whatever camera position
      // was left over from the previous molecule.
      v.zoomTo();
    }
    v.render();
  }, [molecule]);

  // 3Dmol sizes its canvas once, from the container's dimensions at
  // createViewer() time -- it does not observe later container resizes on
  // its own. `height` changing (e.g. ExpandablePanel growing this panel)
  // needs an explicit resize() + render(), or the canvas keeps its old
  // pixel dimensions while the surrounding box grows around it. Also
  // re-frames (zoomTo) so the molecule actually fills the bigger box
  // instead of staying pinned at its old on-screen size -- zoomTo() only
  // rescales camera distance/pan to the current bounding box, it doesn't
  // reset the rotation matrix, so a manual rotation survives this.
  useEffect(() => {
    const v = viewerRef.current;
    if (!v) return;
    v.resize();
    v.zoomTo();
    v.render();
  }, [height]);

  // The capture button lives INSIDE this component rather than being plumbed
  // out through a ref, and that is what makes FR-2 one integration instead of
  // four: NebFrameViewer, EnsembleFrameViewer and ScanFrameViewer all render
  // this component rather than owning a GLViewer of their own, so they inherit
  // the button for free.
  //
  // The wrapper is `relative` for the same load-bearing reason the container
  // itself is (see the comment in ModeAnimationViewer): 3Dmol positions its
  // canvas absolutely, and an absolutely-positioned overlay needs a positioned
  // ancestor of its own or it escapes to the nearest one, which is the drawer.
  return (
    <div className="relative" style={{ height }}>
      <div ref={containerRef} style={{ height }} className="mol-bezel rounded border border-border" />
      {molecule && (
        <DownloadButton
          title="Download this view as a PNG"
          testId="viewer-download-png"
          className="absolute right-1 top-1 z-10 bg-surface/70 backdrop-blur-sm"
          onDownload={() => {
            const v = viewerRef.current;
            if (!v) throw new Error("the viewer is not ready yet");
            downloadDataUri(capturePng(v), `${filenameBase ?? molecule.name ?? "molecule"}_view.png`);
          }}
          onError={onDownloadError}
        />
      )}
    </div>
  );
}
