import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import { jobArtifactUrl, orbitalCubeUrl } from "../lib/api";
import { DownloadButton } from "../app-shell/DownloadButton";
import { downloadDataUri } from "../lib/download";
import { capturePng } from "../molecule/captureViewer";
import type { OrbitalSelection } from "./OrbitalTable";

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
}

export function MoCubeViewer({
  jobId, cubeLabels, orbitalSelection, onClearOrbitalSelection, height = 256, filenameBase,
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
    viewerRef.current = $3Dmol.createViewer(containerRef.current, { backgroundColor: "0x14161a" });
    return () => {
      if (containerRef.current) containerRef.current.innerHTML = "";
      viewerRef.current = null;
    };
  }, []);

  // Fetches the cube text whenever the selected orbital changes -- kept
  // separate from the render effect below so dragging the isoval slider
  // re-renders instantly from the already-fetched text instead of
  // re-fetching (and re-running orca_plot/molden conversion server-side)
  // on every slider tick.
  useEffect(() => {
    const url = orbitalSelection
      ? orbitalCubeUrl(jobId, orbitalSelection.index, orbitalSelection.spin, orbitalSelection.gbw)
      : selected
        ? jobArtifactUrl(jobId, `cubes/${selected}`)
        : null;
    if (!url) return;
    let cancelled = false;
    setCubeLoading(true);
    setCubeError(null);
    // orbitalSelection's URL is a lazy-render POST endpoint (may need to
    // run orca_plot/molden conversion server-side the first time); the
    // label-dropdown path is always a plain GET of an already-rendered
    // cube from job submission.
    fetch(url, { method: orbitalSelection ? "POST" : "GET" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.text();
      })
      .then((text) => {
        if (!cancelled) setCubeText(text);
      })
      .catch((e) => {
        if (!cancelled) setCubeError(String(e));
      })
      .finally(() => {
        if (!cancelled) setCubeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, jobId, orbitalSelection]);

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
    v.addVolumetricData(cubeText, "cube", { isoval, color: "#6e8cff", opacity: 0.85 });
    v.addVolumetricData(cubeText, "cube", { isoval: -isoval, color: "#e85b4e", opacity: 0.85 });
    // Atom numbers, same convention as MoleculeViewer/ModeAnimationViewer --
    // read positions back from the model 3Dmol actually parsed (cube files
    // are in Bohr, and 3Dmol's own cube parser converts to Angstrom; reading
    // model.selectedAtoms() rather than hand-parsing the cube header avoids
    // re-deriving that conversion here). Cube files are written in the same
    // atom order as the job's own molecule, so numbering matches
    // MoleculeViewer's for the same structure.
    model.selectedAtoms({}).forEach((a, i) => {
      v.addLabel(String(i + 1), {
        position: { x: a.x ?? 0, y: a.y ?? 0, z: a.z ?? 0 },
        backgroundColor: "black",
        backgroundOpacity: 0.55,
        fontColor: "white",
        fontSize: 11,
        borderThickness: 0,
        inFront: true,
        showBackground: true,
      });
    });
    if (lastFramedCubeRef.current !== cubeText) {
      v.zoomTo();
      lastFramedCubeRef.current = cubeText;
    }
    v.render();
  }, [cubeText, isoval]);

  // Same reasoning as MoleculeViewer's own resize effect: 3Dmol doesn't
  // observe container size changes on its own, so a height prop change
  // (ExpandablePanel growing this panel) needs an explicit resize(). Also
  // re-frames (zoomTo) here, unlike the isoval-drag render effect above --
  // an expand/collapse toggle is a deliberate "show me this bigger/smaller"
  // action, not an in-place inspection the user is mid-rotating, so
  // rescaling to fill the new box is the wanted behavior (confirmed via
  // Playwright: without this, the model stayed pinned at its old on-screen
  // pixel size in the middle of a much bigger expanded canvas). zoomTo()
  // only adjusts camera distance/pan to fit the current bounding box, not
  // the rotation matrix, so a manual rotation survives the toggle.
  useEffect(() => {
    const v = viewerRef.current;
    if (!v) return;
    v.resize();
    v.zoomTo();
    v.render();
  }, [height]);

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
          <DownloadButton
            title="Download this orbital view as a PNG"
            testId="mocube-download-png"
            className="absolute right-1 top-1 z-10 bg-surface/70 backdrop-blur-sm"
            onDownload={() => {
              const v = viewerRef.current;
              if (!v) throw new Error("the viewer is not ready yet");
              // A table-driven selection is identified by MO index (+ spin for
              // an unrestricted job); the dropdown path has a real label
              // ("HOMO", "LUMO+1"). Name the file after whichever is actually
              // driving the viewer, so the filename matches what is on screen.
              const raw = orbitalSelection
                ? `MO${orbitalSelection.index}${orbitalSelection.spin ? `_${orbitalSelection.spin}` : ""}`
                : selected || "orbital";
              const label = raw.replace(/[^A-Za-z0-9._-]+/g, "_");
              downloadDataUri(capturePng(v), `${filenameBase ?? jobId}_orbital_${label}_view.png`);
            }}
            onError={setCubeError}
          />
        )}
      </div>
      <label className="flex items-center gap-2 text-[10.5px] text-text-muted">
        Isovalue
        <input
          type="range"
          min={0.01}
          max={0.15}
          step={0.005}
          value={isoval}
          onChange={(e) => setIsoval(Number(e.target.value))}
          className="flex-1"
        />
        <span className="w-10 font-mono text-text">{isoval.toFixed(3)}</span>
      </label>
    </div>
  );
}
