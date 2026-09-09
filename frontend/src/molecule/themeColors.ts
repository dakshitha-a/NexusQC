import type { GLViewer } from "3dmol";
import { useAppearanceStore } from "../lib/appearanceStore";

/**
 * The bridge between the CSS theme and 3Dmol, which knows nothing about it.
 *
 * ## Why this exists
 *
 * The viewer background used to be the literal string `"0x14161a"` in three
 * places: fitView's VIEWER_CONFIG, captureViewer's APP_BG, and a comment in
 * each saying they had to match. That was fine while there was exactly one
 * theme. With four, a hardcoded graphite canvas sits in the middle of a paper
 * white panel and looks like a rendering failure.
 *
 * ## Why the background is set rather than the viewer remounted
 *
 * Tearing a 3Dmol viewer down and building a new one leaks its WebGL context.
 * That is the React Strict Mode bug written up in docs/ARCHITECTURE.md, and it
 * was found the hard way; a code-inspection fix for it silently did not work.
 * `setBackgroundColor()` mutates the live viewer, which is the only safe way to
 * do this.
 *
 * ## Hydrogens on a light field
 *
 * 3Dmol's default CPK colouring draws hydrogen white, which is invisible on
 * Daylight's paper background: a water molecule renders as one red sphere with
 * two holes. Rather than rewriting the element colour map, which would mean
 * owning a copy of Jmol's table forever, light themes turn on 3Dmol's own
 * silhouette outline. Every atom keeps its correct CPK colour and gains a dark
 * edge, which is also how a chemist would draw it on paper.
 */

/** Reads a theme token as a 3Dmol colour string, e.g. "#12151a" -> "0x12151a". */
function tokenAsHex(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const m = /^#([0-9a-f]{6})$/i.exec(raw);
  return m ? `0x${m[1]}` : fallback;
}

export function viewerBackground(): string {
  return tokenAsHex("--bg", "0x12151a");
}

/** True on themes whose field is lighter than their ink. */
export function isLightField(): boolean {
  return useAppearanceStore.getState().theme === "daylight";
}

// Which viewers currently carry the light-field outline. 3Dmol has no getter
// for its view style, and calling setViewStyle unconditionally means reaching
// into the renderer on every viewer at creation time even on a dark theme,
// where nothing needs to change. Weak so a viewer that is unmounted is not
// kept alive by this.
const outlined = new WeakSet<GLViewer>();

/**
 * Put a live viewer into the current theme. Safe to call on every appearance
 * change: the background is set unconditionally, and the view style is touched
 * only when it actually has to change.
 */
export function applyViewerTheme(viewer: GLViewer): void {
  viewer.setBackgroundColor(viewerBackground(), 1);
  const wantOutline = isLightField();
  if (wantOutline && !outlined.has(viewer)) {
    viewer.setViewStyle({ style: "outline", color: tokenAsHex("--text", "0x1a1e25"), width: 0.04 });
    outlined.add(viewer);
  } else if (!wantOutline && outlined.has(viewer)) {
    // An empty object is how 3Dmol clears a previously set view style.
    viewer.setViewStyle({});
    outlined.delete(viewer);
  }
  viewer.render();
}

/**
 * Keep a viewer in step with the theme for as long as it is mounted. Returns
 * the unsubscribe function, so a component can hand it straight back from its
 * effect.
 */
export function watchViewerTheme(getViewer: () => GLViewer | null): () => void {
  return useAppearanceStore.subscribe(() => {
    const viewer = getViewer();
    if (viewer) applyViewerTheme(viewer);
  });
}
