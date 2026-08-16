import { Maximize2, Minimize2 } from "lucide-react";
import { useState, type ReactNode } from "react";

/** Wraps a visualization panel (3D viewer, spectrum plot, table) with an
 * expand/collapse toggle that enlarges it in place, without unmounting or
 * reparenting the panel's own DOM subtree. This matters specifically for
 * the 3Dmol-backed viewers (MoleculeViewer/MoCubeViewer/ModeAnimationViewer):
 * portalling them into a Radix Dialog (the obvious "put it in a modal"
 * approach) would unmount their container ref and force a full viewer
 * rebuild -- destroying camera rotation/zoom, re-triggering MoCubeViewer's
 * fetch effect (a real server-side orca_plot/molden re-run, not just a
 * wasted render), and reopening the WebGL-context-leak hazard those
 * components' own mount/cleanup comments already document. Toggling this
 * wrapper's own CSS instead (fixed-position overlay vs. inline) keeps every
 * child component mounted exactly once.
 *
 * `children` is a render-prop receiving the expanded boolean so a caller
 * can pass a bigger `height` to a 3Dmol viewer while expanded (those
 * viewers each have their own resize()-on-height-change effect, since
 * 3Dmol doesn't observe container size changes on its own) -- static
 * content (images, SVG charts) can ignore the flag and simply render
 * wider/taller for free as this wrapper's own box grows. */
export function ExpandablePanel({ children }: { children: (expanded: boolean) => ReactNode }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      {expanded && (
        <div
          className="fixed inset-0 z-50 animate-fade-in bg-black/60"
          onClick={() => setExpanded(false)}
        />
      )}
      <div
        className={
          expanded
            ? "fixed inset-6 z-[60] flex flex-col overflow-auto rounded-lg border border-border bg-surface p-3 shadow-2xl"
            : "relative"
        }
      >
        <button
          onClick={() => setExpanded((e) => !e)}
          title={expanded ? "Collapse" : "Expand"}
          className="absolute right-1 top-1 z-10 rounded bg-surface/80 p-1 text-text-muted hover:bg-surface-raised hover:text-text"
        >
          {expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
        </button>
        <div className={expanded ? "min-h-0 flex-1 overflow-auto pt-6" : ""}>{children(expanded)}</div>
      </div>
    </>
  );
}
