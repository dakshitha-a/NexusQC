#!/usr/bin/env node
// Every colour pair the interface actually draws, checked numerically in all
// four themes.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/ui_14_contrast.spec.mjs
//
// Why this is a spec and not a spreadsheet: the status hues and the accent are
// used as TEXT as well as as fills (text-status-failed on the failure notice,
// text-status-running on the background-turn notice, text-accent on every
// link), and a hue that reads perfectly on graphite can be under 2:1 on paper.
// A light theme cannot be added to this app by eye.
//
// It reads the computed custom properties out of a live page rather than
// parsing index.css, so color-mix() and the [data-theme][data-accent] cascade
// are resolved by the browser exactly as a user would get them.
//
// The bar is WCAG AA (4.5:1) for normal-size text, since every size in this
// app is below the 18.66px bold / 24px normal threshold for "large". The
// Contrast theme is held to AAA (7:1), because being readable at that level is
// the only reason to choose it.
import { BASE_URL, newBrowser, newContext, check, summary } from "./_helpers.mjs";

const AA = 4.5;
const AAA = 7;

function srgbToLinear(c) {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminance([r, g, b]) {
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

function ratio(fg, bg) {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

/** Accepts "#rgb", "#rrggbb" and the "rgb(r, g, b)" the browser returns for a
 *  resolved color-mix(). Alpha is not handled: nothing checked here is
 *  translucent, and silently treating a translucent colour as opaque would
 *  report a contrast the user never sees. */
function parseColor(raw) {
  const s = raw.trim();
  let m = /^#([0-9a-f]{3})$/i.exec(s);
  if (m) return [...m[1]].map((c) => parseInt(c + c, 16));
  m = /^#([0-9a-f]{6})$/i.exec(s);
  if (m) return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
  m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(s);
  if (m) return [1, 2, 3].map((i) => Math.round(Number(m[i])));
  throw new Error(`cannot parse colour: ${raw}`);
}

// Foreground tokens paired with the surfaces they are drawn on. The surface
// list is what the app really does: panels are --surface, the chat column and
// the page are --bg, and hover/selected rows are --surface-raised.
const SURFACES = ["--bg", "--surface", "--surface-raised"];
const ON_SURFACES = [
  "--text",
  "--text-muted",
  "--accent",
  "--status-pending",
  "--status-running",
  "--status-completed",
  "--status-failed",
  "--status-cancelled",
  "--engine-pyscf",
  "--engine-orca",
  "--engine-bagel",
];
// Text drawn on a filled chip of its own colour.
const ON_FILL = [
  ["--on-accent", "--accent"],
  ["--on-status-failed", "--status-failed"],
];

const THEMES = ["balmer", "nightshift", "daylight", "contrast"];
const ACCENTS = ["hbeta", "hgamma", "hdelta", "sodium", "mercury"];

const browser = await newBrowser();

for (const theme of THEMES) {
  const bar = theme === "contrast" ? AAA : AA;
  for (const accent of ACCENTS) {
    const ctx = await newContext(browser);
    await ctx.addInitScript(
      ([k, v]) => {
        try {
          window.localStorage.setItem(k, v);
        } catch (e) {
          /* ignore */
        }
      },
      [
        "qc-agent-appearance",
        JSON.stringify({ state: { theme, accent, fontScale: 1, density: "cosy", motion: "full" }, version: 0 }),
      ],
    );
    const page = await ctx.newPage();
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    const tokens = await page.evaluate((names) => {
      const cs = getComputedStyle(document.documentElement);
      const out = {};
      for (const n of names) out[n] = cs.getPropertyValue(n).trim();
      return out;
    }, [...SURFACES, ...ON_SURFACES, ...ON_FILL.flat()]);

    // The accent swatches only differ from each other in the accent itself, so
    // the surface pairs are checked once per theme rather than five times.
    const fgList = accent === ACCENTS[0] ? ON_SURFACES : ["--accent"];
    for (const fg of fgList) {
      for (const bgName of SURFACES) {
        const r = ratio(parseColor(tokens[fg]), parseColor(tokens[bgName]));
        check(
          `${theme}/${accent}: ${fg} on ${bgName}`,
          r >= bar,
          `${r.toFixed(2)}:1 (need ${bar}) ${tokens[fg]} on ${tokens[bgName]}`,
        );
      }
    }
    for (const [fg, bg] of ON_FILL) {
      if (accent !== ACCENTS[0] && fg !== "--on-accent") continue;
      const r = ratio(parseColor(tokens[fg]), parseColor(tokens[bg]));
      check(`${theme}/${accent}: ${fg} on ${bg}`, r >= bar, `${r.toFixed(2)}:1 (need ${bar})`);
    }
    await ctx.close();
  }
}

await browser.close();
process.exit(summary() ? 0 : 1);
