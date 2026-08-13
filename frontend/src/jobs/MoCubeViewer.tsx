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
    viewerRef.current = $3Dmol.createViewer(containerRef.current, { backgroundColor: "0x14161a" });
    return () => {
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
      <div ref={containerRef} className="h-64 rounded border border-border" />
    </div>
  );
}
