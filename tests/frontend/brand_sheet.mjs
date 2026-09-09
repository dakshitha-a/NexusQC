#!/usr/bin/env node
// Renders docs/brand-sheet.png: the NexusQC mark at every size it is used at,
// on a light and a dark field, in a simulated browser tab, as a lockup, and
// with the spectral lines the palette is derived from.
//
//   node tests/frontend/brand_sheet.mjs
//
// This is the evidence behind the mark's design decisions, and it is a script
// rather than a one-off render so those decisions stay checkable: the reason
// the atom nodes are dropped below 28px is visible in the 16 and 20px cells,
// and the reason the favicon is a separate hand-written file rather than an
// export of Logo.tsx is visible in the tab row.
//
// Deliberately NOT named *.spec.mjs: run_frontend.mjs runs every spec in this
// directory in sequence, and this renders a picture rather than asserting
// anything, so it would only slow a suite run down. It needs no running stack.
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(HERE, "..", "..", "docs", "brand-sheet.png");

// Kept in sync with frontend/src/brand/Logo.tsx by eye, not by import: this
// script runs outside the Vite/React build and cannot resolve a .tsx module.
// If the mark changes there, change it here and re-render.
const ATOM_MIN_PX = 28;
const HEX = "M32 3 58.1 18v30L32 63 5.9 48V18Z";
const CHAIN = "M18 48V17l28 31V17";
const ATOMS = [[18, 48], [18, 17], [46, 48], [46, 17]];
const LINES = [
  ["#34d3ea", "H-beta 486 nm", "accent"],
  ["#2f6fe0", "H-gamma 434 nm", "accent, deep end"],
  ["#ffab2e", "Na-D 589 nm", "running"],
  ["#46d97f", "Hg 546 nm", "completed"],
  ["#ff4f5c", "H-alpha 656 nm", "failed"],
];
const SIZES = [16, 20, 24, 28, 32, 48, 64, 96, 160];

const mark = (s, k) => `<svg viewBox="0 0 64 64" width="${s}" height="${s}">
 <defs><linearGradient id="m${k}" x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
 <stop offset="0" stop-color="#34d3ea"/><stop offset="1" stop-color="#2f6fe0"/></linearGradient></defs>
 <path d="${HEX}" fill="url(#m${k})" stroke="url(#m${k})" stroke-width="5" stroke-linejoin="round"/>
 <path d="${CHAIN}" fill="none" stroke="#0d1117" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
 ${s >= ATOM_MIN_PX ? ATOMS.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3.7" fill="#eaf9ff"/>`).join("") : ""}</svg>`;

const row = (pre) => SIZES.map((s) =>
  `<div class="cell">${mark(s, pre + s)}<span class="cap">${s}px</span></div>`).join("");

const html = `<!doctype html><meta charset="utf-8"><title>NexusQC mark</title><style>
 body{margin:0;font:14px/1.55 system-ui,sans-serif;background:#14161a;color:#e8e6e1}
 .wrap{padding:34px 40px}
 h1{font-size:20px;margin:0 0 4px;font-weight:600}
 .sub{font-size:12.5px;opacity:.55;margin:0 0 26px;max-width:70ch}
 h2{font-size:11px;letter-spacing:.09em;text-transform:uppercase;opacity:.5;font-weight:600;margin:26px 0 12px}
 .row{display:flex;align-items:flex-end;gap:28px;flex-wrap:wrap}
 .cell{display:flex;flex-direction:column;align-items:center;gap:7px}
 .cap{font-size:10px;opacity:.5}
 .light{background:#f7f5f1;color:#1a1d22;border-radius:10px;padding:22px 26px;margin-top:12px}
 .tab{display:inline-flex;align-items:center;gap:8px;background:#fff;color:#3c4043;border-radius:9px 9px 0 0;padding:8px 14px;font-size:12.5px}
 .tab.d{background:#292b2f;color:#e8eaed}
 .lock{display:flex;align-items:center;gap:11px}
 .swatches{display:flex;gap:14px}
 .sw{width:118px}.chip{height:42px;border-radius:8px}
 .swl{font-size:10.5px;opacity:.6;margin-top:5px;font-variant-numeric:tabular-nums}
</style><div class="wrap">
<h1>NexusQC</h1>
<p class="sub">A benzene-shaped tile carrying an N drawn as a three-bond skeletal chain, with an atom at each vertex. The hexagon carries the subject, the letterform carries the name.</p>
<h2>The mark, dark field</h2><div class="row">${row("d")}</div>
<div class="light"><h2 style="opacity:.45">The mark, light field</h2><div class="row">${row("l")}</div></div>
<h2>Browser tab at 16px, the size it has to survive</h2>
<div class="row"><span class="tab">${mark(16, "t1")} NexusQC - Agentic Quantum Chemistry Engine</span>
<span class="tab d">${mark(16, "t2")} NexusQC - Agentic Quantum Chemistry Engine</span></div>
<h2>Lockup</h2><div class="row">
 <div class="lock">${mark(34, "k1")}<span><div style="font-size:17px;font-weight:600;line-height:1.15">NexusQC</div>
 <div style="font-size:11px;opacity:.55;line-height:1.15">Agentic Quantum Chemistry Engine</div></span></div>
 <div class="lock">${mark(24, "k2")}<span style="font-size:14px;font-weight:600">NexusQC</span></div></div>
<h2>Where the colours come from</h2><div class="swatches">${LINES.map(([c, l, role]) =>
  `<div class="sw"><div class="chip" style="background:${c}"></div><div class="swl">${c}<br>${l}<br>${role}</div></div>`).join("")}</div>
</div>`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1180, height: 1000 }, deviceScaleFactor: 2 });
await page.setContent(html);
await page.waitForTimeout(300);
await page.screenshot({ path: OUT, fullPage: true });
await browser.close();
console.log(`wrote ${OUT}`);
