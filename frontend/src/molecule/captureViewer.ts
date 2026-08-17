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

/** A PNG data URI of the viewer's current state. */
export function capturePng(viewer: GLViewer): string {
  viewer.setBackgroundColor(CAPTURE_BG, 1);
  viewer.render();
  try {
    // pngURI() is a bare getCanvas().toDataURL() -- it does NOT render first,
    // so the explicit render above is what puts the white background into the
    // buffer being read. It works at all only because GLViewer.setupRenderer()
    // hardcodes preserveDrawingBuffer: true (the WebGL default is false, which
    // would give a blank image here).
    return viewer.pngURI();
  } finally {
    viewer.setBackgroundColor(APP_BG, 1);
    viewer.render();
  }
}

/**
 * An animated PNG data URI of `frames` rendered frames.
 *
 * APNG rather than GIF, decided in docs/ROADMAP.md: apngURI is built into 3Dmol
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
