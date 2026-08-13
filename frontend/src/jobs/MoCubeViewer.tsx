import { useEffect, useRef, useState } from "react";
import * as $3Dmol from "3dmol";
import type { GLViewer } from "3dmol";
import { jobArtifactUrl } from "../lib/api";

interface Props {
  jobId: string;
  /** orbital labels (the actual cube file lives server-side under
   * artifacts.cubes.<label>; the frontend only needs the labels to
   * populate the selector and build the fetch URL). */
  cubeLabels: string[];
}

export function MoCubeViewer({ jobId, cubeLabels }: Props) {
  const [selected, setSelected] = useState(cubeLabels[0] ?? "");
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

  useEffect(() => {
    const v = viewerRef.current;
    if (!selected || !v) return;
    let cancelled = false;
    fetch(jobArtifactUrl(jobId, `cubes/${selected}`))
      .then((r) => r.text())
      .then((cubeText) => {
        if (cancelled) return;
        v.clear();
        v.addModel(cubeText, "cube");
        v.setStyle({}, { stick: { radius: 0.1 }, sphere: { scale: 0.25 } });
        // Both signs of the orbital lobe, standard MO-visualization convention.
        v.addVolumetricData(cubeText, "cube", { isoval: 0.04, color: "#6e8cff", opacity: 0.85 });
        v.addVolumetricData(cubeText, "cube", { isoval: -0.04, color: "#e85b4e", opacity: 0.85 });
        v.zoomTo();
        v.render();
      });
    return () => {
      cancelled = true;
    };
  }, [selected, jobId]);

  return (
    <div className="flex flex-col gap-2">
      <select
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
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
    </div>
  );
}
