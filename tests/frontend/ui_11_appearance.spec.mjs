#!/usr/bin/env node
// The appearance panel: four themes, five accents, five text sizes, three
// densities and a motion switch, all of which have to reach the DOM, survive a
// reload, and be applied before the first paint rather than after it.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/ui_11_appearance.spec.mjs
//
// Three of these checks exist for specific ways this can look fine and be
// broken:
//
// - The pre-paint check loads a page with a non-default theme already saved
//   and reads the root element's attributes while #root is still empty. If the
//   inline script in index.html were removed, zustand's persist middleware
//   would still apply the theme, just one paint late, and every load would
//   flash the wrong app. Nothing else here would notice.
// - The theme checks read the COMPUTED background of <body>, not the attribute.
//   Setting data-theme is easy; having every compiled Tailwind utility follow
//   it is the thing that can silently stop working, and it depends on
//   index.css using `@theme inline` so the utilities keep their var()
//   indirection.
// - The viewer check requires the 3D canvas to repaint AND to still be the
//   same canvas element afterwards. Rebuilding the viewer would also change
//   the picture, while leaking its WebGL context, which is the Strict Mode bug
//   docs/ARCHITECTURE.md describes.
import {
  BASE_URL,
  ADMIN_USER,
  adminPassword,
  newBrowser,
  newContext,
  LOGGED_IN,
  check,
  summary,
} from "./_helpers.mjs";

const KEY = "qc-agent-appearance";
const saved = (over = {}) =>
  JSON.stringify({
    state: { theme: "balmer", accent: "hbeta", fontScale: 1, density: "cosy", motion: "full", ...over },
    version: 0,
  });

/** Every theme's --bg, as index.css defines it. Written out rather than read
 *  from the page, so a token accidentally deleted shows up as a failure here
 *  instead of as "the value equals itself". */
const THEME_BG = {
  balmer: "rgb(18, 21, 26)",
  nightshift: "rgb(23, 19, 14)",
  daylight: "rgb(244, 242, 236)",
  contrast: "rgb(0, 0, 0)",
};

const browser = await newBrowser();

// --- 1. Applied before the app renders --------------------------------------
{
  const ctx = await newContext(browser);
  await ctx.addInitScript(([k, v]) => window.localStorage.setItem(k, v), [KEY, saved({ theme: "daylight", fontScale: 1.2 })]);
  const page = await ctx.newPage();
  await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
  const early = await page.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    scale: document.documentElement.style.getPropertyValue("--font-scale"),
  }));
  check("pre-paint script sets the theme", early.theme === "daylight", `data-theme=${early.theme}`);
  check("pre-paint script sets the text scale", early.scale === "1.2", `--font-scale=${early.scale}`);
  await ctx.close();
}

// The point of that script is that it runs WITHOUT the bundle. A module script
// is deferred, so it always executes before DOMContentLoaded and #root is
// never empty by the time a test can look: "React has not rendered yet" is not
// observable. Blocking the bundle outright is, and it is the stronger claim
// anyway. If the inline script were deleted, this is the check that would go
// red while everything else here stayed green, because zustand would still
// apply the theme, just one paint late.
{
  const ctx = await newContext(browser);
  await ctx.addInitScript(([k, v]) => window.localStorage.setItem(k, v), [KEY, saved({ theme: "contrast" })]);
  await ctx.route("**/assets/*.js", (route) => route.abort());
  const page = await ctx.newPage();
  await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
  const themed = await page.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    children: document.getElementById("root")?.childElementCount ?? -1,
    bg: getComputedStyle(document.body).backgroundColor,
  }));
  check(
    "with the bundle blocked entirely, the page is still themed",
    themed.theme === "contrast" && themed.bg === "rgb(0, 0, 0)",
    `data-theme=${themed.theme}, body ${themed.bg}, #root children ${themed.children}`,
  );
  await ctx.close();
}

// --- 2. Everything the panel changes ----------------------------------------
const ctx = await newContext(browser);
const page = await ctx.newPage();
await page.setViewportSize({ width: 1600, height: 1000 });
await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
await page.fill('input[type="password"]', adminPassword());
await page.click('[data-testid="auth-submit"]');
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });

check(
  "the palette control is in the sidebar header",
  await page.locator('[data-testid="rail-appearance"]').isVisible(),
);
await page.click('[data-testid="rail-appearance"]');
await page.waitForSelector('[data-testid="appearance-theme-balmer"]', { timeout: 5000 });

const rootStyle = (prop) =>
  page.evaluate((p) => getComputedStyle(document.documentElement).getPropertyValue(p).trim(), prop);
const bodyBg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

for (const [id, expected] of Object.entries(THEME_BG)) {
  await page.click(`[data-testid="appearance-theme-${id}"]`);
  await page.waitForTimeout(120);
  const attr = await page.evaluate(() => document.documentElement.dataset.theme);
  const bg = await bodyBg();
  check(`theme ${id} reaches the root element`, attr === id, `data-theme=${attr}`);
  check(`theme ${id} repaints the page`, bg === expected, `body background ${bg}, expected ${expected}`);
}
await page.click('[data-testid="appearance-theme-balmer"]');

// The panel's own swatches are rendered in the themes they name, so the four
// previews must not all be the same colour as each other.
const previewBgs = await page.evaluate(() =>
  ["balmer", "nightshift", "daylight", "contrast"].map((id) => {
    const el = document.querySelector(`[data-testid="appearance-theme-${id}"] [data-theme]`);
    return el ? getComputedStyle(el).backgroundColor : null;
  }),
);
check(
  "each theme card previews its own colours",
  new Set(previewBgs).size === 4 && !previewBgs.includes(null),
  previewBgs.join(" / "),
);

const accentBefore = await rootStyle("--accent");
await page.click('[data-testid="appearance-accent-sodium"]');
await page.waitForTimeout(120);
const accentAfter = await rootStyle("--accent");
check("choosing an accent changes it", accentAfter !== accentBefore, `${accentBefore} -> ${accentAfter}`);
check("and the accent is the sodium line", accentAfter.toLowerCase() === "#ffab2e", accentAfter);
await page.click('[data-testid="appearance-accent-hbeta"]');

const fontBefore = await page.evaluate(() => getComputedStyle(document.documentElement).fontSize);
await page.click('[data-testid="appearance-fontscale-135"]');
await page.waitForTimeout(120);
const fontAfter = await page.evaluate(() => getComputedStyle(document.documentElement).fontSize);
check("the text size lever moves the root font size", fontAfter !== fontBefore, `${fontBefore} -> ${fontAfter}`);
check("and by the factor it says", fontAfter === "21.6px", fontAfter);
// Panel widths are rem, so the sidebar has to have grown with it.
const railWidth = await page.evaluate(
  () => document.querySelector('[data-testid="conversation-list"]')?.closest("div[style]")?.getBoundingClientRect().width ?? 0,
);
check("the sidebar grows with the text", railWidth > 288, `${Math.round(railWidth)}px`);
await page.click('[data-testid="appearance-fontscale-1"]');

const spacingBefore = await rootStyle("--spacing");
await page.click('[data-testid="appearance-density-compact"]');
await page.waitForTimeout(120);
const spacingAfter = await rootStyle("--spacing");
check("density changes Tailwind's spacing unit", spacingAfter !== spacingBefore, `${spacingBefore} -> ${spacingAfter}`);
await page.click('[data-testid="appearance-density-cosy"]');

await page.click('[data-testid="appearance-motion-reduced"]');
await page.waitForTimeout(120);
check(
  "asking for stillness reaches the root element",
  (await page.evaluate(() => document.documentElement.dataset.motion)) === "reduced",
);
const stilled = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="appearance-theme-balmer"]');
  return getComputedStyle(el).transitionDuration;
});
check(
  "and actually neutralises transitions",
  parseFloat(stilled) < 0.001,
  `transition-duration ${stilled}`,
);
await page.click('[data-testid="appearance-motion-full"]');

// --- 3. It survives a reload ------------------------------------------------
await page.click('[data-testid="appearance-theme-nightshift"]');
await page.click('[data-testid="appearance-accent-mercury"]');
await page.waitForTimeout(150);
await page.reload({ waitUntil: "networkidle" });
check(
  "the choice survives a reload",
  (await page.evaluate(() => document.documentElement.dataset.theme)) === "nightshift" &&
    (await rootStyle("--accent")).toLowerCase() === "#46d97f",
);

// --- 4. Keyboard focus is visible -------------------------------------------
const outline = await page.evaluate(() => {
  const el = document.querySelector('[data-testid="rail-appearance"]');
  el.focus();
  // :focus-visible only matches a focus the browser judges keyboard-driven;
  // el.focus() from script counts, which is why this is read here rather than
  // after a synthetic click.
  const cs = getComputedStyle(el);
  return { width: cs.outlineWidth, style: cs.outlineStyle };
});
check(
  "keyboard focus draws a visible ring",
  outline.style === "solid" && parseFloat(outline.width) >= 1,
  `${outline.style} ${outline.width}`,
);

// --- 5. The 3D viewer follows, without being rebuilt ------------------------
await page.keyboard.press("Escape");
await page.waitForTimeout(400);
const hasCanvas = await page.locator("canvas").first().isVisible().catch(() => false);
if (!hasCanvas) {
  check("a molecule viewer is on screen to test", false, "no visible canvas; open a conversation with a molecule");
} else {
  const snap = () =>
    page.evaluate(() => {
      const c = Array.from(document.querySelectorAll("canvas")).find((x) => x.offsetParent !== null);
      if (!c) return null;
      c.dataset.themeProbe = c.dataset.themeProbe || "marked";
      try {
        return { uri: c.toDataURL(), probe: c.dataset.themeProbe };
      } catch {
        return null;
      }
    });
  const before = await snap();
  await page.click('[data-testid="rail-appearance"]');
  await page.waitForSelector('[data-testid="appearance-theme-daylight"]', { timeout: 5000 });
  await page.click('[data-testid="appearance-theme-daylight"]');
  await page.waitForTimeout(600);
  const after = await snap();
  check("the viewer repaints when the theme changes", before && after && before.uri !== after.uri);
  check(
    "and it is the same canvas, so the WebGL context was not rebuilt",
    after?.probe === "marked",
    `probe=${after?.probe}`,
  );
  await page.click('[data-testid="appearance-theme-balmer"]');
}

// --- 6. Reset -----------------------------------------------------------------
await page.click('[data-testid="appearance-reset"]');
await page.waitForTimeout(150);
check(
  "reset puts everything back",
  await page.evaluate(() => {
    const r = document.documentElement;
    return r.dataset.theme === "balmer" && r.dataset.accent === "hbeta" && r.dataset.density === "cosy";
  }),
);

await ctx.close();
await browser.close();
process.exit(summary() ? 0 : 1);
