#!/usr/bin/env node
// Screenshot sweep of the app in every theme and at the ends of the text-size
// range, for looking at rather than asserting on.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/ui_shots.mjs
//   ... --only=balmer            just one theme
//   ... --out=/tmp/shots         somewhere other than docs/e2e-artifacts/ui
//
// A passing Playwright assertion says a control exists and behaves. It cannot
// say the panel is legible, that a hue survived a theme swap, or that a row
// stopped fitting at the largest text size, and those are the failures this
// redesign is most likely to produce. So every phase gate renders this and the
// images get looked at.
//
// Not named *.spec.mjs on purpose: run_frontend.mjs runs every spec in this
// directory and this asserts nothing.
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { BASE_URL, ADMIN_USER, adminPassword, newBrowser, newContext, LOGGED_IN } from "./_helpers.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(
  process.argv.slice(2).filter((a) => a.startsWith("--")).map((a) => a.replace(/^--/, "").split("=")),
);
const OUT = args.out || path.resolve(HERE, "..", "..", "docs", "e2e-artifacts", "ui");
const THEMES = args.only ? [args.only] : ["balmer", "nightshift", "daylight", "contrast"];
// 1366x900 is where the three-panel row starts to bind, which is the width the
// text-size range has to survive; 1920 is what it is normally used at.
const VIEWPORTS = [
  { name: "1366", width: 1366, height: 900 },
  { name: "1920", width: 1920, height: 1080 },
];

/** Written into localStorage before any page script runs, in the exact shape
 *  zustand's persist middleware uses, so the pre-paint script in index.html
 *  picks it up and the app is already themed on first paint. */
const appearance = (theme, fontScale = 1, density = "cosy") =>
  JSON.stringify({ state: { theme, accent: "hbeta", fontScale, density, motion: "full" }, version: 0 });

mkdirSync(OUT, { recursive: true });

const browser = await newBrowser();
const shots = [];

async function shoot(page, name) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  shots.push(file);
  console.log(`  ${name}.png`);
}

// The sign-in screen, which renders before the shell exists and therefore has
// to be themed by the pre-paint script alone.
for (const theme of THEMES) {
  const ctx = await newContext(browser);
  await ctx.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    ["qc-agent-appearance", appearance(theme)],
  );
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="auth-form-login"]', { timeout: 15000 });
  await shoot(page, `login-${theme}`);
  await ctx.close();
}

// The shell, signed in, in each theme and at both ends of the text-size range.
const CASES = [];
for (const theme of THEMES) CASES.push({ theme, fontScale: 1, vp: VIEWPORTS[1] });
CASES.push({ theme: "balmer", fontScale: 0.9, vp: VIEWPORTS[0] });
CASES.push({ theme: "balmer", fontScale: 1.35, vp: VIEWPORTS[0] });

for (const { theme, fontScale, vp } of CASES) {
  const ctx = await newContext(browser);
  await ctx.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    ["qc-agent-appearance", appearance(theme, fontScale)],
  );
  const page = await ctx.newPage();
  await page.setViewportSize({ width: vp.width, height: vp.height });
  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
  await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
  await page.fill('input[type="password"]', adminPassword());
  await page.click('[data-testid="auth-submit"]');
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await page.waitForTimeout(1200);
  const tag = `shell-${theme}-fs${String(fontScale).replace(".", "")}-${vp.name}`;
  await shoot(page, tag);
  await ctx.close();
}

await browser.close();
console.log(`\n${shots.length} screenshots in ${OUT}`);
