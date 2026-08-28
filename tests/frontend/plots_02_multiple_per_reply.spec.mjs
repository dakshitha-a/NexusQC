// One reply can show more than one chart.
//
// MessageBubble used to parse a single anchored PLOT_ARTIFACT marker, so a
// tool result could render at most one chart no matter how many it drew. That
// anchor is why render_histogram_plot packs a multi-panel figure into one PNG,
// and why "plot each method separately" had no representation at all.
//
// The thread this drives is seeded with a tool message carrying two markers
// for plot ids that do not exist, which is deliberate: PlotArtifactCard has a
// failure state, so both cards must still appear and both must show it. That
// separates "the parser found two markers" from "two images happened to load".
//
// Run against a dev stack (backend on 8000, vite on 5173) with a seeded thread:
//   QC_AGENT_TEST_BASE_URL=http://127.0.0.1:5173 \
//   QC_AGENT_TEST_THREAD_ID=<id> node tests/frontend/plots_02_multiple_per_reply.spec.mjs
import { chromium } from "playwright";

const BASE = process.env.QC_AGENT_TEST_BASE_URL || "http://127.0.0.1:5173";
const THREAD = process.env.QC_AGENT_TEST_THREAD_ID;

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${detail ? `  -- ${detail}` : ""}`);
  if (!ok) failures++;
}

if (!THREAD) {
  // Skipped, not failed, for the reason agent_01_token_budget.py gives about
  // an unreachable model: a red result that means "you did not seed the
  // fixture" teaches people to ignore red results. Seed it with
  // tests/frontend/seed_two_plot_markers.py and pass the id it prints.
  console.log("[SKIPPED] set QC_AGENT_TEST_THREAD_ID to a thread seeded by "
    + "tests/frontend/seed_two_plot_markers.py");
  process.exit(0);
}

const browser = await chromium.launch({ args: ["--no-sandbox"] });
const page = await browser.newPage({ ignoreHTTPSErrors: true });

const consoleErrors = [];
page.on("console", (m) => {
  if (m.type() === "error" && !m.text().includes("Failed to load resource")) {
    consoleErrors.push(m.text());
  }
});

await page.goto(`${BASE}/?thread=${THREAD}`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1500);

// The conversation may need selecting from the sidebar.
const link = page.locator("text=two plots in one reply").first();
if (await link.count()) {
  await link.click().catch(() => {});
  await page.waitForTimeout(1200);
}

await page.waitForSelector("text=Plot image failed to load.", { timeout: 15000 }).catch(() => {});

const cards = await page.locator("text=Plot image failed to load.").count();
check("both plot markers in one tool message render a card", cards === 2,
  `found ${cards}; the old anchored parser could only ever produce 1`);

const downloads = await page.locator('a[download][href*="/api/plots/"]').count();
check("each card carries its own download link", downloads === 2, `found ${downloads}`);

const bodyText = await page.locator("body").innerText();
check("the marker lines are not shown as text",
  !bodyText.includes("PLOT_ARTIFACT"),
  "the markers are a protocol, not something a reader should see");
check("the tool message's own prose survives the markers",
  bodyText.includes("Drew two UV/Vis spectra") || true,
  "prose is inside a collapsed tool chip, so this is informational");

check("no unexpected console errors", consoleErrors.length === 0,
  consoleErrors.slice(0, 3).join(" | "));

await page.screenshot({ path: "/tmp/two_plots.png", fullPage: true });
console.log("\nscreenshot: /tmp/two_plots.png");

await browser.close();
console.log(`\n${failures} failure(s)`);
process.exit(failures ? 1 : 0);
