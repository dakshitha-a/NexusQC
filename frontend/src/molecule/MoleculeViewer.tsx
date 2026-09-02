import { useEffect, useRef } from "react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import type { MoleculeDict } from "../lib/api";
import { DownloadButton } from "../app-shell/DownloadButton";
import { ViewerOverlay } from "../app-shell/ExpandablePanel";
import { downloadDataUri } from "../lib/download";
import { jobDownloadName, slugifyLabel } from "../lib/jobFilename";
import { useViewerPrefsStore } from "../lib/viewerPrefsStore";
import { AtomLabelToggle } from "./AtomLabelToggle";
import { applyAtomLabels } from "./atomLabels";
import { capturePng } from "./captureViewer";
import { VIEWER_CONFIG, fitView, useViewerAutoFit } from "./fitView";

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
  descriptor = "view",
  onDownloadError,
  showLabelToggle = true,
}: {
  molecule: MoleculeDict | null;
  height?: number;
  // Caller-supplied stem for a captured PNG, so a download lands as
  // "20260817_water_Opt_B3LYP_def2-SVP_ORCA_78a32a61_view.png" rather than
  // just "water_view.png". Optional: this component is also used outside any
  // job context (the molecule panel), where the molecule's own name is the
  // best available answer.
  filenameBase?: string;
  // The middle word of the download name, i.e. the "descriptor" in
  // safename_descriptor.extension. Defaults to the whole-molecule case. The
  // frame viewers override it with the frame they are showing, because four
  // captures off one scan otherwise arrive as four files called ..._view.png
  // that nothing but their order distinguishes.
  descriptor?: string;
  onDownloadError?: (message: string) => void;
  // MoleculePanel sets this false for its inline viewer: its own header row
  // already carries the switch a couple of inches above, and two of them in
  // one panel reads as two separate settings. Everywhere else -- including
  // that panel's enlarged flyout, where the header row is behind the
  // overlay -- the viewer's corner is the only place it can be.
  showLabelToggle?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const lastKeyRef = useRef<string | null>(null);
  const atomLabels = useViewerPrefsStore((s) => s.atomLabels);

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
    viewerRef.current = $3Dmol.createViewer(containerRef.current, VIEWER_CONFIG);
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
      // The atom numbers are NOT drawn here. They belong to the effect
      // below, which is keyed on the atom-label preference as well as on
      // the molecule -- see its own comment for why they cannot live in
      // this one.
      // Unconditional, not gated to the first render: fires on every real
      // model rebuild (i.e. whenever the content-hash key above actually
      // changed) so a molecule swapped in later -- e.g. a geometry
      // optimization's final coordinates replacing the input structure --
      // is properly framed instead of inheriting whatever camera position
      // was left over from the previous molecule.
      fitView(v);
    }
    v.render();
  }, [molecule]);

  // Atom numbers, on their own effect rather than folded into the rebuild
  // above. The rebuild is guarded by a content hash and re-frames the camera
  // (`fitView`) whenever it does run, so putting `atomLabels` in ITS
  // dependency array gives one of two wrong behaviours: the hash guard bails
  // out early and the switch does nothing, or the guard is loosened and every
  // flip of the switch throws away the rotation and zoom the user set. Labels
  // are cheap scene objects that can be added and removed against a live
  // viewer, so they simply do not belong to the same unit of work.
  //
  // `molecule` stays in the dependencies even though this effect reads only
  // the coordinates: the rebuild above calls removeAllLabels(), so a molecule
  // swap has to be followed by this effect re-laying them. Effects run in
  // declaration order within a commit, so that ordering holds.
  useEffect(() => {
    const v = viewerRef.current;
    if (!v) return;
    const positions = molecule
      ? molecule.coords.map(([x, y, z]) => ({ x, y, z }))
      : [];
    applyAtomLabels(v, positions, atomLabels);
    v.render();
  }, [molecule, atomLabels]);

  // Container resizes -- the panel being expanded, or LeftRail/RightDock
  // being drag-resized -- are handled by a ResizeObserver rather than an
  // effect keyed on `height`, which only ever saw the first of those. See
  // useViewerAutoFit's own comment.
  useViewerAutoFit(containerRef, viewerRef);

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
        <ViewerOverlay>
          {showLabelToggle && (
            <AtomLabelToggle testId="viewer-atom-labels" className="bg-surface/70 backdrop-blur-sm" />
          )}
          <DownloadButton
            title="Download this view as a PNG"
            testId="viewer-download-png"
            className="bg-surface/70 backdrop-blur-sm"
            onDownload={() => {
              const v = viewerRef.current;
              const c = containerRef.current;
              if (!v || !c) throw new Error("the viewer is not ready yet");
              // slugifyLabel on the fallback too: molecule.name is free text
              // ("1,3-butadiene", or whatever a user typed), and this viewer is
              // also used outside the job drawer, where there is no stem.
              downloadDataUri(
                capturePng(v, c),
                jobDownloadName(
                  filenameBase ?? (slugifyLabel(molecule.name ?? "") || "molecule"),
                  descriptor,
                  ".png",
                ),
              );
            }}
            onError={onDownloadError}
          />
        </ViewerOverlay>
      )}
    </div>
  );
}
