import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * How the app looks: theme, accent, text size, density and motion.
 *
 * ## How it reaches the CSS
 *
 * Nothing here is passed down through React. Every setting is stamped onto
 * `<html>` as an attribute or a custom property, and index.css does the rest,
 * because `@theme inline` keeps the `var()` indirection in every compiled
 * Tailwind utility. Changing one attribute on the root element repaints the
 * whole app, including panels nobody has touched, with no rebuild.
 *
 * ## Why the same values are also written in index.html
 *
 * zustand's `persist` middleware rehydrates from localStorage *after* the
 * first React render, so a saved preference would land one paint too late and
 * every load would flash the defaults. index.html carries a small inline
 * script that reads this exact key and stamps the same attributes before the
 * bundle is even fetched. **The key name and the persisted shape below are a
 * contract with that script**: change either and the flash comes back, quietly.
 *
 * ## Why this is separate from layoutStore
 *
 * layoutStore is about where things are (which panels are open, how wide they
 * are). This is about how they look. They persist under different keys so that
 * resetting one does not throw away the other.
 */

export type ThemeId = "balmer" | "nightshift" | "daylight" | "contrast";
export type AccentId = "hbeta" | "hgamma" | "hdelta" | "sodium" | "mercury";
export type DensityId = "compact" | "cosy" | "roomy";
export type MotionId = "full" | "reduced";

/** The key the inline script in index.html reads. Do not rename in one place. */
export const APPEARANCE_KEY = "qc-agent-appearance";

export const THEMES: { id: ThemeId; name: string; blurb: string }[] = [
  { id: "balmer", name: "Balmer", blurb: "Graphite field. The default." },
  { id: "nightshift", name: "Nightshift", blurb: "Warm and low blue, for working late." },
  { id: "daylight", name: "Daylight", blurb: "Paper and ink, for a bright room or a projector." },
  { id: "contrast", name: "Contrast", blurb: "Pure black, brightened. Checked at AAA." },
];

/**
 * Accents are named for the emission line each is taken from, which is also
 * where the status colours come from. `hgamma` is the accent the app shipped
 * with, kept so nobody loses the look they were used to.
 */
export const ACCENTS: { id: AccentId; name: string; line: string }[] = [
  { id: "hbeta", name: "Cyan", line: "H-beta, 486 nm" },
  { id: "hgamma", name: "Periwinkle", line: "H-gamma, 434 nm" },
  { id: "hdelta", name: "Violet", line: "H-delta, 410 nm" },
  { id: "sodium", name: "Amber", line: "sodium D, 589 nm" },
  { id: "mercury", name: "Green", line: "mercury, 546 nm" },
];

/** Five steps rather than a free slider: every one has been looked at in a
 *  browser at 1366px, which is where the three-panel row starts to bind. */
export const FONT_SCALES: { value: number; label: string }[] = [
  { value: 0.9, label: "Small" },
  { value: 1, label: "Default" },
  { value: 1.1, label: "Large" },
  { value: 1.2, label: "Larger" },
  { value: 1.35, label: "Largest" },
];

export const DENSITIES: { id: DensityId; name: string; blurb: string }[] = [
  { id: "compact", name: "Compact", blurb: "Tighter padding. More rows on screen." },
  { id: "cosy", name: "Cosy", blurb: "The default spacing." },
  { id: "roomy", name: "Roomy", blurb: "More air between controls." },
];

export interface AppearanceState {
  theme: ThemeId;
  accent: AccentId;
  fontScale: number;
  density: DensityId;
  motion: MotionId;
  setTheme: (theme: ThemeId) => void;
  setAccent: (accent: AccentId) => void;
  setFontScale: (fontScale: number) => void;
  setDensity: (density: DensityId) => void;
  setMotion: (motion: MotionId) => void;
  reset: () => void;
}

export const APPEARANCE_DEFAULTS = {
  theme: "balmer" as ThemeId,
  accent: "hbeta" as AccentId,
  fontScale: 1,
  density: "cosy" as DensityId,
  motion: "full" as MotionId,
};

/**
 * Stamp the settings onto `<html>`. The inline script in index.html is the
 * same six lines, written out longhand there because it has to run before any
 * module loads.
 */
export function applyAppearance(s: {
  theme: ThemeId;
  accent: AccentId;
  fontScale: number;
  density: DensityId;
  motion: MotionId;
}): void {
  const root = document.documentElement;
  root.dataset.theme = s.theme;
  root.dataset.accent = s.accent;
  root.dataset.density = s.density;
  root.dataset.motion = s.motion;
  root.style.setProperty("--font-scale", String(s.fontScale));
}

export const useAppearanceStore = create<AppearanceState>()(
  persist(
    (set) => ({
      ...APPEARANCE_DEFAULTS,
      setTheme: (theme) => set({ theme }),
      setAccent: (accent) => set({ accent }),
      setFontScale: (fontScale) => set({ fontScale }),
      setDensity: (density) => set({ density }),
      setMotion: (motion) => set({ motion }),
      reset: () => set({ ...APPEARANCE_DEFAULTS }),
    }),
    { name: APPEARANCE_KEY },
  ),
);

// Applied here rather than from a component effect so it happens once, at
// module load, and cannot be missed by a component that fails to mount (the
// sign-in screen renders before the shell exists, and it needs the theme too).
applyAppearance(useAppearanceStore.getState());
useAppearanceStore.subscribe(applyAppearance);
