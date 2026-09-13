import { viewerBackground } from "./themeColors";
import { useEffect } from "react";
import type { GLViewer } from "3dmol";

/**
 * Camera framing for every 3Dmol viewer in the app, in one place.
 *
 * ## Why this exists: molecules loaded small, and it was not our code
 *
 * Every viewer already called `zoomTo()` on load, so "nothing frames the
 * molecule" was never the problem. Measuring 3Dmol's own behaviour headlessly
 * (a two-atom dimer, sweeping the separation) showed the camera distance was
 * *identical* -- `getView()[3] == 121.644` -- at 0.5 A, 1 A, 5 A and 10 A
 * separation, and only started tracking size above 10 A. Reading the library
 * source explains it exactly:
 *
 *     // 3dmol/build/3Dmol.js, GLViewer.zoomTo()
 *     var MAXD = this.config.minimumZoomToDistance || 5;
 *     ...
 *     var maxDsq = MAXD * MAXD;              // floor on the bounding radius
 *     for (...) if (dsq > maxDsq) maxDsq = dsq;
 *     maxD = Math.sqrt(maxDsq) * 2;
 *
 * The fit is on a sphere of radius `max(MAXD, r_max)`, and MAXD defaults to
 * 5 A. So EVERY molecule with a bounding radius under 5 A -- water, benzene,
 * and most of what this app actually runs -- was framed as though it were 10 A
 * across. Water measured at 6% of the frame width; benzene at 39%. That is the
 * whole of the "always zoomed out and small" report, and it is a library
 * default, not a bug in the viewers.
 *
 * `minimumZoomToDistance` is a supported config option, so the fix is to pass
 * a floor low enough that it stops binding for real molecules. It cannot be 0:
 * the floor is what keeps a single-atom system (r_max == 0) from putting the
 * camera at the origin.
 *
 * ## Why there is also a margin
 *
 * With the floor lowered, 3Dmol's own fit turns out to *clip*: benzene
 * measured 0.769 x 0.993 of the frame with content touching the edge. That is
 * inherent to the fit -- it measures atom CENTRES and knows nothing about the
 * sphere radii, sticks and atom-number labels drawn around them.
 *
 * So the framing pulls back by a fixed fraction. A *fraction* is the important
 * part: it is scale-invariant, so it behaves identically on water and on a
 * 40-atom system. A constant offset (the tempting `zoom(1.2)`) would not --
 * tuned on water it would overshoot everything larger, trading a reported bug
 * for an unreported one. Measured across water, benzene and a ~19 A in-plane
 * chain, each 0.05 step of this factor moves all three by the same ~5%, and
 * 0.85 is the largest value where none of the three clips.
 */
const FIT_MARGIN = 0.85;

/** Shared `createViewer` config. The background is read from `--bg` at the
 * moment the viewer is built rather than hardcoded, so a viewer created while
 * Daylight is active starts on paper instead of starting graphite and being
 * corrected a frame later. Keeping it in step afterwards is watchViewerTheme's
 * job (see themeColors.ts), which mutates the live viewer rather than
 * rebuilding it: a rebuilt viewer leaks its WebGL context. */
export function viewerConfig() {
  return {
    backgroundColor: viewerBackground(),
    minimumZoomToDistance: 1.0,
  } as const;
}

/**
 * Frame the whole scene: every atom, and every shape's bounding sphere.
 *
 * Deliberately passes no selection. `zoomTo()` folds each shape's bounding
 * sphere into the fit (see its `this.shapes.forEach` block), which is what
 * keeps MoCubeViewer's two volumetric isosurfaces in frame -- they extend well
 * past the atoms, and grow further as the isovalue drops. Narrowing this to
 * the atoms would clip the orbital lobes, i.e. the exact thing that panel
 * exists to show.
 *
 * Does not touch the rotation matrix, so a manual rotation survives a re-fit.
 */
export function fitView(viewer: GLViewer): void {
  viewer.zoomTo();
  viewer.zoom(FIT_MARGIN);
}

/**
 * Keep a 3Dmol canvas sized to, and framed within, its container.
 *
 * 3Dmol sizes its canvas once, from the container's dimensions at
 * `createViewer()` time, and never observes the container again. Each viewer
 * used to compensate with an effect keyed on its `height` prop, which covered
 * exactly one case (ExpandablePanel growing the panel) and missed the other:
 * LeftRail and RightDock are both drag-resizable, so dragging the dock changed
 * the container's WIDTH and nothing ever called `resize()` -- the canvas kept
 * its old pixel width inside a box that had grown or shrunk around it.
 *
 * A ResizeObserver covers both, and the initial delivery it makes on observe()
 * also re-frames once the container has its real size, rather than whatever it
 * measured mid-layout.
 */
export function useViewerAutoFit(
  containerRef: React.RefObject<HTMLDivElement | null>,
  viewerRef: React.RefObject<GLViewer | null>,
): void {
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let frame = 0;
    // rAF-coalesced: a drag-resize delivers a burst of entries, and resize()
    // rebuilds the renderer's buffers -- doing that per pointer-move event is
    // both wasteful and visibly janky.
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const v = viewerRef.current;
        if (!v || el.clientWidth === 0 || el.clientHeight === 0) return;
        v.resize();
        fitView(v);
        v.render();
      });
    });
    observer.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [containerRef, viewerRef]);
}

/**
 * The nearest thing to a `destroy()` that 3Dmol 2.5.5 offers from outside.
 *
 * `GLViewer` has no teardown method, and its constructor registers five things
 * it never removes: `mouseup` and `touchend` on `document.body`, `resize` on
 * `window`, a `ResizeObserver` on the container and an `IntersectionObserver`
 * on the container. Clearing the container's `innerHTML` in cleanup detaches
 * the canvas and drops this app's own reference, but those five bindings are a
 * separate and stronger reference: the viewer, its scene graph and its
 * geometry buffers stay reachable for the life of the page.
 *
 * Two of the five can be removed from here, and they are the two that cost
 * something visible. Both observers watch the container, and the container is
 * a stable `<div>` that survives a viewer swap, so after any rebuild the
 * orphan's observers fire on the same element as the live viewer's and the
 * orphan runs a full `resize()`: re-read the box, `setSize()` on the renderer,
 * re-render into a canvas nobody can see. Every window resize does the same to
 * every orphan ever created. Disconnecting them stops that work and removes
 * the container-side reference.
 *
 * The `document.body` and `window` listeners cannot be removed, because the
 * bound functions were never stored anywhere. Removing the residual needs an
 * upstream `destroy()`. This is documented in docs/ARCHITECTURE.md rather than
 * quietly accepted.
 */
export function releaseViewer(viewer: GLViewer | null): void {
  if (!viewer) return;
  const v = viewer as unknown as {
    divwatcher?: { disconnect?: () => void };
    intwatcher?: { disconnect?: () => void };
  };
  try {
    v.divwatcher?.disconnect?.();
    v.intwatcher?.disconnect?.();
  } catch {
    // A library version without these fields is not a reason to break unmount.
  }
}
