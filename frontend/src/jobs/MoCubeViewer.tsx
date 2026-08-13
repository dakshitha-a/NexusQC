import { useEffect, useRef, useState } from "react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import { jobArtifactUrl, orbitalCubeUrl } from "../lib/api";
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
}

export function MoCubeViewer({ jobId, cubeLabels, orbitalSelection, onClearOrbitalSelection }: Props) {
  const [selected, setSelected] = useState(cubeLabels[0] ?? "");
  const [cubeText, setCubeText] = useState<string | null>(null);
  const [isoval, setIsoval] = useState(0.04);
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
      ? orbitalCubeUrl(jobId, orbitalSelection.index, orbitalSelection.spin)
      : selected
        ? jobArtifactUrl(jobId, `cubes/${selected}`)
        : null;
    if (!url) return;
    let cancelled = false;
    // orbitalSelection's URL is a lazy-render POST endpoint (may need to
    // run orca_plot/molden conversion server-side the first time); the
    // label-dropdown path is always a plain GET of an already-rendered
    // cube from job submission.
    fetch(url, { method: orbitalSelection ? "POST" : "GET" })
      .then((r) => r.text())
      .then((text) => {
        if (!cancelled) setCubeText(text);
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
    v.clear();
    v.addModel(cubeText, "cube");
    v.setStyle({}, { stick: { radius: 0.1 }, sphere: { scale: 0.25 } });
    // Both signs of the orbital lobe, standard MO-visualization convention.
    v.addVolumetricData(cubeText, "cube", { isoval, color: "#6e8cff", opacity: 0.85 });
    v.addVolumetricData(cubeText, "cube", { isoval: -isoval, color: "#e85b4e", opacity: 0.85 });
    if (lastFramedCubeRef.current !== cubeText) {
      v.zoomTo();
      lastFramedCubeRef.current = cubeText;
    }
    v.render();
  }, [cubeText, isoval]);

  return (
    <div className="flex flex-col gap-2">
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
      {/* relative is load-bearing here -- see ModeAnimationViewer.tsx's
          comment: without an actually-positioned container, 3Dmol's canvas
          escapes to this drawer's `fixed` root instead of staying inside
          this box. */}
      <div ref={containerRef} className="relative h-64 rounded border border-border" />
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
