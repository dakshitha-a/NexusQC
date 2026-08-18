// Capturing what a 3D viewer is currently showing.
//
// This is a different mechanism from the Download buttons that already exist:
// those serve server-rendered matplotlib artifacts over ordinary links. What is
// on screen here -- the camera the user rotated to, the zoom, the isovalue they
// picked, the frame the animation is on -- exists only in the browser, and no
// server-side render can reproduce it. That is the whole point of these.
import type { GLViewer } from "3dmol";

// Papers and slides have white pages, and the app's surface is near-black.
// Exporting the dark background would make every captured figure need editing.
const CAPTURE_BG = "white";
const APP_BG = 0x14161a; // matches createViewer({backgroundColor: "0x14161a"}) in every viewer

// FR-2's still capture is exactly the on-screen canvas by default -- fine for
// slides, lowish for print. This multiplies the container's on-screen CSS box
// before rendering, so the exported bitmap is sharper than what is on screen
// without changing what the user sees there.
//
// The cap is on the FINAL backing-store pixels, not on the CSS size we ask
// for: GLViewer.setWidth/setHeight (via setSize, in 3Dmol's WebGLRenderer)
// multiply whatever width/height we pass by a further ratio to get the
// actual canvas.width/height, so naively requesting EXPORT_SCALE * cssSize
// could silently ask the GPU for far more than that and exceed a modest
// GPU's max renderable size. That further ratio is NOT reliably
// window.devicePixelRatio: confirmed live in a headless Chromium context
// reporting devicePixelRatio=1 where the canvas's actual backing store was
// still 2x its container's CSS box (3Dmol's own antialias-driven upscaling,
// or a headless-specific quirk -- either way, not visible from JS as
// window.devicePixelRatio). capturePng() below measures the viewer's
// CURRENT ratio directly off its own canvas rather than predicting it. 4096px
// is comfortably under the WebGL MAX_TEXTURE_SIZE/MAX_RENDERBUFFER_SIZE floor
// guaranteed by the spec (2048) combined with what virtually every GPU still
// in service actually reports.
const EXPORT_SCALE = 3;
const MAX_EXPORT_EDGE_PX = 4096;

// THE ORDERING BELOW IS LOAD-BEARING, in both functions.
//
// setBackgroundColor() itself triggers a render, and apngURI() captures on
// EVERY render (it works by hooking viewChangeCallback, which fires from
// show()). So a background swap made after the hook is installed lands a stray
// dark frame at the head of the animation:
//
//     set white -> render() -> [capture / hook apngURI] -> await -> restore -> render()
//
// The same order is used for the still capture purely so the two read alike.

/**
 * A PNG data URI of the viewer's current state -- same camera, zoom, isovalue
 * and frame as what's on screen, rendered at up to `EXPORT_SCALE`x the
 * on-screen resolution (capped at `MAX_EXPORT_EDGE_PX` per edge of the actual
 * backing-store bitmap, not the CSS size requested).
 *
 * `container` is the element whose on-screen CSS box defines the capture's
 * baseline resolution and, afterward, what GLViewer.resize() restores to --
 * it's the same element the caller already holds a ref to for mounting the
 * viewer (see MoleculeViewer.tsx/MoCubeViewer.tsx), not read from `viewer`
 * itself: GLViewer's own width/height accessors are private in its type
 * declarations, and the container's real box is the more direct source of
 * truth for "what size is this on screen right now" than trying to recover
 * it from the viewer's internal state.
 */
export function capturePng(viewer: GLViewer, container: HTMLElement): string {
  const cssW = container.clientWidth;
  const cssH = container.clientHeight;
  // Measure the viewer's CURRENT backing-store-to-CSS ratio directly off its
  // own canvas rather than predicting it from window.devicePixelRatio -- see
  // the constants' comment above for why that prediction can be wrong.
  // getCanvas() is public (unlike WIDTH/HEIGHT, which aren't).
  const canvas = viewer.getCanvas();
  const effectiveRatio = cssW > 0 && canvas.width > 0 ? canvas.width / cssW : window.devicePixelRatio || 1;
  const scale =
    cssW > 0 && cssH > 0 ? Math.min(EXPORT_SCALE, MAX_EXPORT_EDGE_PX / (Math.max(cssW, cssH) * effectiveRatio)) : 1;
  const resized = scale > 1;
  if (resized) {
    // Both calls are load-bearing, not just the second: setWidth/setHeight
    // each call updateSize() -> renderer.setSize(), which sets BOTH the
    // canvas's backing-store resolution (what pngURI's toDataURL reads) AND
    // its CSS display size -- momentarily growing the on-screen element.
    // That's invisible to the user because this whole function runs
    // synchronously with no `await`: nothing yields back to the browser's
    // paint loop between here and the `finally` block's viewer.resize()
    // snapping it back, the same ordering guarantee the background-color
    // swap above already relies on.
    viewer.setWidth(Math.round(cssW * scale));
    viewer.setHeight(Math.round(cssH * scale));
  }
  viewer.setBackgroundColor(CAPTURE_BG, 1);
  viewer.render();
  try {
    // pngURI() is a bare getCanvas().toDataURL() -- it does NOT render first,
    // so the explicit render above is what puts the white background (and,
    // if resized, the larger buffer) into what gets read. It works at all
    // only because GLViewer.setupRenderer() hardcodes
    // preserveDrawingBuffer: true (the WebGL default is false, which would
    // give a blank image here).
    return viewer.pngURI();
  } finally {
    viewer.setBackgroundColor(APP_BG, 1);
    // resize() re-reads the container's actual current box and snaps the
    // viewer back to it -- simpler and more robust than caching the
    // pre-capture WIDTH/HEIGHT ourselves (those aren't part of GLViewer's
    // public type surface anyway), and correct even if the container was
    // itself resized during the capture. It does NOT re-run fitView()/zoomTo()
    // (confirmed by reading GLViewer.resize()'s source), so a manual
    // rotation/zoom/pan the user set before downloading survives this call --
    // and useViewerAutoFit's ResizeObserver (fitView.ts), which DOES re-fit,
    // watches `container` itself, which setWidth/setHeight above never touch
    // (only the canvas element inside it), so it never fires from this.
    if (resized) viewer.resize();
    viewer.render();
  }
}

/**
 * An animated PNG data URI of `frames` rendered frames.
 *
 * APNG rather than GIF, a deliberate choice: apngURI is built into 3Dmol
 * and encodes via upng-js, already a hard dependency, where a true GIF would
 * cost the gif.js library, this app's first web worker, and 256-colour
 * quantisation that dithers visibly on smooth 3D shading. The trade-off
 * accepted with it: browsers, Slack and GitHub animate an APNG; PowerPoint and
 * Word show only its first frame.
 *
 * The timeout is not optional. apngURI resolves only after exactly `frames`
 * viewChangeCallback invocations, and those only happen while something is
 * rendering -- against a paused or static viewer it never resolves at all, and
 * the button would spin forever with no error.
 */
export async function captureApng(viewer: GLViewer, frames = 40, timeoutMs = 20_000): Promise<string> {
  viewer.setBackgroundColor(CAPTURE_BG, 1);
  viewer.render();
  try {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error("the viewer stopped rendering before the capture finished")),
        timeoutMs,
      );
    });
    try {
      // 3Dmol types apngURI's resolution as `unknown`; it is documented and
      // implemented as a base64 data URI (upng-js output).
      return (await Promise.race([viewer.apngURI(frames), timeout])) as string;
    } finally {
      clearTimeout(timer);
    }
  } finally {
    viewer.setBackgroundColor(APP_BG, 1);
    viewer.render();
  }
}
