import { Maximize2, Minimize2, X } from "lucide-react";
import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** The one control cluster a visualization panel gets, top-right.
 *
 * This exists because two independent components both claimed `absolute
 * right-1 top-1 z-10`: ExpandablePanel's own expand toggle (below) and the
 * DownloadButton each 3D viewer overlays on itself. Equal z-index means DOM
 * order decides, the viewer's button is the later sibling, and it carries a
 * `bg-surface/70 backdrop-blur-sm` -- so it painted straight over the expand
 * toggle in every molecule, orbital and vibration panel. The plots were
 * unaffected only because they happen to have no overlay control of their own.
 *
 * Offsetting one button to `right-8` would have fixed the instance and left
 * the defect class untouched: the next overlay control added anywhere would
 * re-collide, and nothing in the tree would say why the offset existed. So
 * the panel owns exactly one absolutely-positioned row and everything else
 * renders *into* it, in flow. That is the same reasoning ShellLayout.tsx
 * records for F-013 -- flow layout inside one container beats a z-index arms
 * race, because it cannot silently regress.
 */
const OverlaySlotContext = createContext<HTMLElement | null>(null);

/** Where that one row is allowed to sit.
 *
 * Its natural home is the panel's own top-right corner, and for a panel whose
 * visualization starts at the top (a spectrum image, a frame viewer) that
 * corner IS the visualization's corner. Two panels are not shaped like that:
 * the orbital viewer has a label dropdown above its box, and the vibrations
 * panel has the frequency table above it collapsed and beside it expanded. In
 * both, the row floated over that other content rather than over the thing it
 * controls, which is how the download and expand buttons ended up somewhere
 * other than the corner of the viewer they belong to.
 *
 * So a viewer may nominate its own box, and the whole row moves there.
 * Deliberately the whole row: offsetting one button to dodge another is the
 * exact anti-pattern the comment above rejects, and one row with one owner is
 * what keeps it rejected. */
const AnchorContext = createContext<((el: HTMLElement | null) => void) | null>(null);

/** Puts the enclosing panel's control row in this viewer's own top-right
 * corner instead of the panel's. Renders an empty positioned box for the row
 * to be portalled into, and nothing at all when there is no ExpandablePanel
 * above it, so a viewer used bare still works.
 *
 * Belongs inside a `relative` box; every 3Dmol viewer already has one for its
 * own reasons (see ModeAnimationViewer's comment on why). */
export function PanelControlAnchor() {
  const register = useContext(AnchorContext);
  if (!register) return null;
  // A callback ref feeding the panel's state, never a plain ref -- same
  // lesson `slot` below records: a ref is null on the render that matters and
  // notifies nobody when it stops being, so the row would stay in the panel
  // corner forever.
  return <span ref={register} className="absolute right-1 top-1 z-20 flex items-center gap-1" />;
}

/** Renders viewer controls into the enclosing ExpandablePanel's control row,
 * alongside (and left of) its expand toggle. Falls back to positioning itself
 * in the same corner when there is no ExpandablePanel above it -- MoleculeViewer
 * is used both inside a panel (the job drawer) and bare (the molecule panel),
 * and must look right either way.
 *
 * The portal does not break event handling: React portals keep the child in
 * the React tree it was declared in, so a click on a control here bubbles
 * through that component's handlers and never reaches the expand toggle it is
 * now a DOM sibling of. */
export function ViewerOverlay({ children }: { children: ReactNode }) {
  const slot = useContext(OverlaySlotContext);
  const row = <div className="flex items-center gap-1">{children}</div>;
  if (slot) return createPortal(row, slot);
  return <div className="absolute right-1 top-1 z-10 flex items-center gap-1">{row}</div>;
}

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
export function ExpandablePanel({
  children,
  name,
}: {
  children: (expanded: boolean) => ReactNode;
  /** Optional identity for this panel, surfaced as `data-panel` on the
   * wrapper. Every panel's expand toggle carries the same
   * `data-testid="panel-expand"` -- which is right, since it is the same
   * control -- so a test that wants *one particular* panel's toggle had no
   * way to say which, and resorted to "the last one in the drawer". That
   * silently retargets the moment a section is added below. The attribute
   * survives expanding, because expanding restyles this div rather than
   * replacing it. */
  name?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  // State, not a ref: ViewerOverlay's portal target has to be a value the
  // consumers re-render against once the node exists. A ref would be null on
  // the render that matters and never notify anyone when it stopped being.
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  // The box a child viewer nominated for the control row, if it did. State
  // for exactly the same reason `slot` is.
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  const controls = (
    <>
      <span ref={setSlot} className="flex items-center gap-1" />
      {/* Additive, not a replacement for the toggle below: that button is
          asserted on by title="Collapse" in the viewer-control specs, so it
          keeps its existing icon/title/behavior untouched. This is a
          conventional close affordance (same X lucide-react uses in
          Flyout.tsx/MoleculeBuilderModal.tsx) for the fullscreen overlay,
          which otherwise offers no visibly-labeled way out of it. */}
      {expanded && (
        <button
          onClick={() => setExpanded(false)}
          title="Close"
          data-testid="panel-close"
          className="rounded bg-surface/80 p-1 text-text-muted hover:bg-surface-raised hover:text-text"
        >
          <X size={13} />
        </button>
      )}
      <button
        onClick={() => setExpanded((e) => !e)}
        title={expanded ? "Collapse" : "Expand"}
        data-testid="panel-expand"
        className="rounded bg-surface/80 p-1 text-text-muted hover:bg-surface-raised hover:text-text"
      >
        {expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
      </button>
    </>
  );

  return (
    <>
      {expanded && (
        <div
          className="fixed inset-0 z-50 animate-fade-in bg-black/60"
          onClick={() => setExpanded(false)}
        />
      )}
      <div
        data-panel={name}
        className={
          expanded
            ? "fixed inset-6 z-[60] flex flex-col overflow-auto rounded-lg border border-border bg-surface p-3 shadow-2xl"
            : "relative"
        }
      >
        {/* One row, z-20: above any content the panel wraps, and the single
            place any overlay control in this panel is allowed to live. The
            toggle stays rightmost because it is the constant -- the viewer
            controls to its left vary by panel. It renders in this panel's own
            corner unless a child nominated a box of its own (see
            PanelControlAnchor), in which case the whole row is portalled
            there. */}
        {anchor ? (
          createPortal(controls, anchor)
        ) : (
          <div className="absolute right-1 top-1 z-20 flex items-center gap-1">{controls}</div>
        )}
        <AnchorContext.Provider value={setAnchor}>
          <OverlaySlotContext.Provider value={slot}>
            {/* Expanded, the top padding is what clears the control row
                floating in this panel's corner. Anchored inside a viewer
                there is no such row up there to clear, and the padding would
                only be a gap. */}
            <div className={expanded ? `min-h-0 flex-1 overflow-auto ${anchor ? "" : "pt-6"}` : ""}>
              {children(expanded)}
            </div>
          </OverlaySlotContext.Provider>
        </AnchorContext.Provider>
      </div>
    </>
  );
}
