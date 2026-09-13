import { applyViewerTheme, watchViewerTheme } from "../molecule/themeColors";
import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import { checkRawResponse, jobArtifactUrl, orbitalCubeUrl } from "../lib/api";
import { DownloadButton } from "../app-shell/DownloadButton";
import { PanelControlAnchor, ViewerOverlay } from "../app-shell/ExpandablePanel";
import { downloadDataUri } from "../lib/download";
import { jobDownloadName } from "../lib/jobFilename";
import { useViewerPrefsStore } from "../lib/viewerPrefsStore";
import { AtomLabelToggle } from "../molecule/AtomLabelToggle";
import { applyAtomLabels, type LabelPosition } from "../molecule/atomLabels";
import { capturePng } from "../molecule/captureViewer";
import { viewerConfig, fitView, useViewerAutoFit } from "../molecule/fitView";
import type { OrbitalSelection } from "./OrbitalTable";

/** How long a selection has to hold still before its cube is fetched. Long
 * enough that the intermediate orbitals a drag passes over are never
 * requested, short enough to be invisible on a single row click. */
const SETTLE_MS = 200;

/** Laplacian smoothing passes over the marching-cubes mesh.
 *
 * 3Dmol's default is 1 (GLShape.addIsosurface), which is not enough to remove
 * the staircase the grid cells leave behind: lobes came out visibly corrugated,
 * and the corrugation was the cube's own voxel structure showing through rather
 * than anything in the wavefunction. Both cube paths write a fixed 80 points
 * per axis (orca_plot's ngrid, and pyscf cubegen's nx/ny/nz) over a box that
 * grows with the molecule, so the spacing coarsens as systems get bigger --
 * measured 0.076 Bohr for water against 0.195 Bohr for benzene -- and the
 * ripples coarsen with it.
 *
 * Smoothing rather than a denser grid because this costs nothing and applies to
 * every job already on disk, where 160 points per axis would be eight times the
 * data to render server-side and to transfer on every lazy orbital fetch.
 *
 * The trade-off, stated because it is real: Laplacian smoothing pulls vertices
 * inward, so the drawn surface sits fractionally inside the true isosurface.
 * Measured on rendered lobe area, 1.4% for water and 3.1% for benzene at this
 * value, i.e. one to two percent in linear extent. That is well inside what
 * moving the isovalue slider one notch does, and the alternative is a surface
 * whose visible texture is an artifact of the grid. */
const ISO_SMOOTHNESS = 6;

interface Props {
  jobId: string;
  /** orbital labels (the actual cube file lives server-side under
   * artifacts.cubes.<label>; the frontend only needs the labels to
   * populate the selector and build the fetch URL). */
  cubeLabels: string[];
  /** Controlled selection from an OrbitalTable row click -- when set, takes
   * priority over the label dropdown below and fetches lazily via POST
   * /api/jobs/{id}/orbitals/{index}/cube instead of the label-keyed
   * artifacts.cubes GET path (see server/routes/jobs.py's
   * get_orbital_cube). Both paths render into the same viewer -- OrbitalTable
   * lets a user inspect any orbital, not just the ones eagerly rendered at
   * job-submission time. */
  orbitalSelection?: OrbitalSelection | null;
  /** Called when the label dropdown is used directly, so the parent can
   * clear orbitalSelection -- otherwise a stale table selection would keep
   * outranking the dropdown (see the fetch effect below) and the dropdown
   * would silently stop doing anything after a table row was ever clicked. */
  onClearOrbitalSelection?: () => void;
  /** Pixel height of the viewer box (default 256, i.e. Tailwind's h-64) --
   * lets a caller (e.g. ExpandablePanel) grow the viewer when expanded. */
  height?: number;
  /** Stem for a captured PNG, so it lands under the job's own name rather
   * than its id. See frontend/src/lib/jobFilename.ts. */
  filenameBase?: string;
  /** Move the enclosing panel's control row into this viewer's own corner.
   * Opt-in per call site rather than always, because this viewer is not
   * always the panel's subject: in the orbitals panel it is, and the row
   * belongs over the isosurface, but in a neb_ts panel it is a secondary
   * per-frame inspector below the path viewer, and dragging the whole
   * panel's expand toggle down into it would be nonsense. */
  anchorPanelControls?: boolean;
}

export function MoCubeViewer({
  jobId, cubeLabels, orbitalSelection, onClearOrbitalSelection, height = 256, filenameBase,
  anchorPanelControls = false,
}: Props) {
  const [selected, setSelected] = useState(cubeLabels[0] ?? "");
  const [cubeText, setCubeText] = useState<string | null>(null);
  const [isoval, setIsoval] = useState(0.04);
  // A lazy per-orbital cube (orbitalSelection's POST path) can trigger a
  // server-side orca_plot/molden conversion the first time it's requested
  // -- previously there was no feedback during that wait, so the viewer
  // just kept showing whatever the last-rendered orbital was with no cue
  // that a new one was on the way.
  const [cubeLoading, setCubeLoading] = useState(false);
  const [cubeError, setCubeError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const atomLabels = useViewerPrefsStore((s) => s.atomLabels);
  // Atom positions as 3Dmol parsed them out of the cube file, kept for the
  // label effect below. A ref rather than state because writing it must not
  // itself cause a render: it is filled by the render effect, and the only
  // effect that reads it already re-runs on everything that can change it.
  const labelPositionsRef = useRef<LabelPosition[]>([]);

  useEffect(() => {
    if (!containerRef.current) return;
    // See the detailed comment in molecule/MoleculeViewer.tsx -- clearing
    // here (before creating a viewer), not just in cleanup, is what
    // actually prevents a leaked WebGL context: React 18 Strict Mode's
    // mount->cleanup->remount dance already nulls containerRef.current by
    // the time cleanup runs, which would make a cleanup-only clear silently
    // do nothing while the DOM node (and its orphaned <canvas>) persists
    // across the cycle. This viewer also mounts/unmounts every time the job
    // detail drawer opens/closes, so it leaks even faster than the
    // always-mounted molecule panel if this isn't handled.
    containerRef.current.innerHTML = "";
    viewerRef.current = $3Dmol.createViewer(containerRef.current, viewerConfig());
    // A light theme needs 3Dmol's silhouette outline or CPK hydrogens, drawn
    // white, vanish into the paper background. Applied at creation and kept in
    // step afterwards by mutating this viewer rather than rebuilding it: a
    // rebuilt viewer leaks its WebGL context, which is the Strict Mode bug
    // described above and in docs/ARCHITECTURE.md.
    applyViewerTheme(viewerRef.current);
    const stopThemeWatch = watchViewerTheme(() => viewerRef.current);
    return () => {
      stopThemeWatch();
      if (containerRef.current) containerRef.current.innerHTML = "";
      viewerRef.current = null;
    };
  }, []);

  // The selection, taken apart into its primitive fields, because the effect
  // below must depend on those and never on the object itself. Both callers
  // hand over a freshly-built object: JobDetailDrawer's orbital scrubber calls
  // setSelectedOrbital({...}) on every pointermove -- and a slow drag produces
  // dozens of those *within one orbital's slice of the track*, all naming the
  // same orbital -- while NebFrameViewer passes an inline literal, which is a
  // new object on every render of its parent, i.e. on every job poll. With the
  // object in the dependency array React compared by reference, so each of
  // those re-fired the fetch, and each re-fire is a real orca_plot or
  // molden->cube run on the server. That is what left this viewer spinning
  // after a scrubber drag: a hundred-odd POSTs queued behind the browser's
  // six-connections-per-origin limit, with the one the user was actually
  // waiting for at the back of the queue.
  const selIndex = orbitalSelection?.index ?? null;
  const selSpin = orbitalSelection?.spin ?? null;
  const selGbw = orbitalSelection?.gbw ?? null;

  // Fetches the cube text whenever the selected orbital changes -- kept
  // separate from the render effect below so dragging the isoval slider
  // re-renders instantly from the already-fetched text instead of
  // re-fetching (and re-running orca_plot/molden conversion server-side)
  // on every slider tick.
  useEffect(() => {
    const url =
      selIndex != null
        ? orbitalCubeUrl(jobId, selIndex, selSpin, selGbw)
        : selected
          ? jobArtifactUrl(jobId, `cubes/${selected}`)
          : null;
    if (!url) return;
    let cancelled = false;
    const controller = new AbortController();
    setCubeLoading(true);
    setCubeError(null);
    // Wait for the selection to settle before asking the server for anything.
    // A scrubber drag walks through every orbital between where it started and
    // where it ends up; without this, each intermediate one spawns its own
    // server-side render for a view the user never stops on -- on a shared
    // host, dozens of orca_plot subprocesses for nothing. The delay is
    // imperceptible next to an actual cube render, and putting it here rather
    // than in FrameScrubber keeps that control generic: its other consumers
    // (scan, NEB and vibrational-mode frames) are pure client-side redraws and
    // must not get slower.
    const timer = setTimeout(() => {
      // The per-orbital URL is a lazy-render POST endpoint (may need to run
      // orca_plot or a molden conversion server-side the first time); the
      // label-dropdown path is always a plain GET of an already-rendered cube
      // from job submission.
      fetch(url, { method: selIndex != null ? "POST" : "GET", signal: controller.signal })
        .then((r) => checkRawResponse(r, "Couldn't load the orbital"))
        .then((r) => r.text())
        .then((text) => {
          if (!cancelled) setCubeText(text);
        })
        .catch((e) => {
          if (!cancelled) setCubeError(String(e));
        })
        .finally(() => {
          if (!cancelled) setCubeLoading(false);
        });
    }, SETTLE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      // Abort, don't merely ignore. A superseded fetch that is only ignored
      // still holds one of the browser's six connections to this origin until
      // the server is done with it, which is why a drag stalled job polling
      // and the SSE stream alongside the viewer itself.
      controller.abort();
    };
  }, [selected, jobId, selIndex, selSpin, selGbw]);

  // Re-renders on every cubeText/isoval change, but only re-frames the
  // camera (zoomTo) when the cube itself changed -- otherwise dragging the
  // isoval slider would reset any manual rotation/zoom on every tick.
  const lastFramedCubeRef = useRef<string | null>(null);
  useEffect(() => {
    const v = viewerRef.current;
    if (!v || !cubeText) return;
    v.clear(); // also wipes labels -- must re-add below on every run, not just the first
    const model = v.addModel(cubeText, "cube");
    v.setStyle({}, { stick: { radius: 0.1 }, sphere: { scale: 0.25 } });
    // Both signs of the orbital lobe, standard MO-visualization convention.
    v.addVolumetricData(cubeText, "cube", { isoval, color: "#6e8cff", opacity: 0.85, smoothness: ISO_SMOOTHNESS });
    v.addVolumetricData(cubeText, "cube", {
      isoval: -isoval, color: "#e85b4e", opacity: 0.85, smoothness: ISO_SMOOTHNESS,
    });
    // Atom positions read back from the model 3Dmol actually parsed, because
    // cube files are in Bohr and 3Dmol's own cube parser converts to
    // Angstrom; taking model.selectedAtoms() rather than hand-parsing the
    // cube header avoids re-deriving that conversion here. Cube files are
    // written in the same atom order as the job's own molecule, so the
    // numbering matches MoleculeViewer's for the same structure. The labels
    // themselves are drawn by the effect below, not here.
    labelPositionsRef.current = model
      .selectedAtoms({})
      .map((a) => ({ x: a.x ?? 0, y: a.y ?? 0, z: a.z ?? 0 }));
    if (lastFramedCubeRef.current !== cubeText) {
      // fitView deliberately frames the shapes as well as the atoms -- the
      // two isosurfaces added just above extend past the atoms, and further
      // still as the isovalue drops. See fitView.ts.
      fitView(v);
      lastFramedCubeRef.current = cubeText;
    }
    v.render();
  }, [cubeText, isoval]);

  // Atom numbers, same 1-based convention as MoleculeViewer and
  // ModeAnimationViewer, drawn from the positions the effect above stashed.
  //
  // `isoval` is in the dependencies even though no label depends on it, and
  // that is the whole point: the effect above calls `v.clear()`, which wipes
  // the labels along with the model and the isosurfaces, and it re-runs on
  // every tick of the isovalue slider. Keyed on `[cubeText, atomLabels]`
  // alone, the numbers would disappear the moment anybody touched that
  // slider and never come back. This list has to cover everything the
  // rebuild above reacts to.
  //
  // Separate from that effect rather than folded into it because the
  // rebuild deliberately re-frames the camera only when the cube itself
  // changed, so that dragging the isovalue does not throw away a manual
  // rotation. Toggling the labels must not either.
  useEffect(() => {
    const v = viewerRef.current;
    if (!v || !cubeText) return;
    applyAtomLabels(v, labelPositionsRef.current, atomLabels);
    v.render();
  }, [cubeText, isoval, atomLabels]);

  // Re-frames on any container resize, unlike the isoval-drag render effect
  // above: an expand/collapse or a dock drag is a deliberate "show me this
  // bigger/smaller" action, not an in-place inspection the user is mid-
  // rotating, so rescaling to fill the new box is the wanted behaviour
  // (confirmed via Playwright: without this the model stayed pinned at its
  // old on-screen pixel size in the middle of a much bigger canvas). The fit
  // does not touch the rotation matrix, so a manual rotation survives it.
  useViewerAutoFit(containerRef, viewerRef);

  return (
    <div className="flex flex-col gap-2">
      {cubeLabels.length > 0 && (
        <select
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            onClearOrbitalSelection?.();
          }}
          className="rounded border border-border bg-surface px-2 py-1 text-xs text-text"
        >
          {cubeLabels.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
      )}
      {/* relative is load-bearing here -- see ModeAnimationViewer.tsx's
          comment: without an actually-positioned container, 3Dmol's canvas
          escapes to this drawer's `fixed` root instead of staying inside
          this box. */}
      <div className="relative rounded border border-border" style={{ height }}>
        {/* Keeps the download and expand buttons in this box's corner rather
            than the panel's, which is above the orbital dropdown and nowhere
            near the orbital they act on. */}
        {anchorPanelControls && <PanelControlAnchor />}
        <div ref={containerRef} className="absolute inset-0" />
        {cubeLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-bg/60 text-text-muted animate-fade-in">
            <Loader2 size={20} className="animate-spin" />
          </div>
        )}
        {cubeError && !cubeLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-bg/80 p-2 text-center text-xs text-status-failed">
            Couldn't load orbital: {cubeError}
          </div>
        )}
        {/* Captures the CURRENT state -- this orbital, at this isovalue, from
            this camera. That is exactly what no server-rendered image can
            reproduce, and why the isovalue slider below is worth capturing
            alongside the view. */}
        {cubeText && !cubeLoading && (
          <ViewerOverlay>
            <AtomLabelToggle testId="mocube-atom-labels" className="bg-surface/70 backdrop-blur-sm" />
            <DownloadButton
              title="Download this orbital view as a PNG"
              testId="mocube-download-png"
              className="bg-surface/70 backdrop-blur-sm"
              onDownload={() => {
                const v = viewerRef.current;
                const c = containerRef.current;
                if (!v || !c) throw new Error("the viewer is not ready yet");
                // A table-driven selection is identified by MO index (+ spin for
                // an unrestricted job); the dropdown path has a real label
                // ("HOMO", "LUMO+1"). Name the file after whichever is actually
                // driving the viewer, so the filename matches what is on screen.
                const label = orbitalSelection
                  ? `MO${orbitalSelection.index}${orbitalSelection.spin ? `_${orbitalSelection.spin}` : ""}`
                  : selected || "orbital";
                downloadDataUri(
                  capturePng(v, c),
                  jobDownloadName(filenameBase ?? jobId, `orbital_${label}_view`, ".png"),
                );
              }}
              onError={setCubeError}
            />
          </ViewerOverlay>
        )}
      </div>
      <label className="flex items-center gap-2 text-3xs text-text-muted">
        Isovalue
        <input
          type="range"
          min={0.01}
          max={0.15}
          step={0.005}
          value={isoval}
          onChange={(e) => setIsoval(Number(e.target.value))}
          data-testid="mocube-isoval"
          className="qc-range flex-1"
        />
        <span className="w-10 font-mono text-text">{isoval.toFixed(3)}</span>
      </label>
    </div>
  );
}
