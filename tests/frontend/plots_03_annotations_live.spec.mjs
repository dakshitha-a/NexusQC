/**
 * Asking for labelled values on a plot, end to end, in a real browser.
 *
 * On 2026-09-24 a user asked for "the energies for each method" on a levels
 * plot, the agent's annotations were silently dropped, and the same session
 * sat on a bare spinner for 106 s before an empty reply. This drives one real
 * turn against the served model and checks what the user sees:
 *
 *   1. "Thinking..." is on screen while the model works, and once a wait
 *      passes three seconds it carries a running count of seconds
 *      (reported, not failed, if every wait in the turn was shorter).
 *   2. The reply ends with a plot that actually loads inline in the chat,
 *      judged by the <img>'s naturalWidth rather than a screenshot.
 *   3. The plot record the agent saved asks for value_labels or
 *      annotations, so the numbers are on the plot and not in the x labels.
 *
 * The rendered PNG and a screenshot of the chat are saved for a human look.
 * The thread and every plot it drew are deleted at the end.
 *
 *   THREAD=$(docker exec -i -e QC_AGENT_TEST_JOB_IDS=<ids> <api> python3 - < tests/frontend/seed_annotation_thread.py)
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 QC_AGENT_TEST_THREAD_ID=$THREAD \
 *     node tests/frontend/plots_03_annotations_live.spec.mjs
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { newBrowser, newContext, adminApiLogin, check, summary, BASE_URL, LOGGED_IN } from "./_helpers.mjs";

const THREAD = process.env.QC_AGENT_TEST_THREAD_ID;
if (!THREAD) {
  console.log("[SKIPPED] set QC_AGENT_TEST_THREAD_ID to a thread seeded by seed_annotation_thread.py");
  process.exit(0);
}
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "plots03-"));

const browser = await newBrowser();
const context = await newContext(browser);
await adminApiLogin(context);
const page = await context.newPage();
await page.goto(`${BASE_URL}/?thread=${THREAD}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
await page.waitForTimeout(1500);

// Plot images already on the page (the Plots panel's thumbnails, and any
// earlier reply) are not the answer. An earlier version of this spec took the
// last /api/plots/ image anywhere on the page, read a panel thumbnail as the
// reply, and then tried to delete that unrelated plot during cleanup.
const CHAT_PLOT = 'img[alt="Plot"][src*="/api/plots/"]';
const before = new Set(await page.$$eval(CHAT_PLOT, (imgs) => imgs.map((i) => i.getAttribute("src"))));
const ORIGIN = { headers: { Origin: BASE_URL } };

const box = page.locator("textarea").first();
await box.fill("Plot the S1 and S2 excitation energies of the attached jobs as an energy-level "
  + "diagram, one column per method, and write each energy on its level.");
await box.press("Enter");

let sawThinking = false;
let sawCount = false;
let lastCount = "";
let plotSrc = null;
const started = Date.now();
while (Date.now() - started < 6 * 60 * 1000) {
  if (await page.locator('[data-testid="agent-thinking"]').count()) sawThinking = true;
  const count = page.locator('[data-testid="agent-thinking-elapsed"]');
  if (await count.count()) {
    sawCount = true;
    lastCount = (await count.first().innerText()).trim();
    if (lastCount && !fs.existsSync(path.join(outDir, "thinking.png"))) {
      await page.screenshot({ path: path.join(outDir, "thinking.png") });
    }
  }
  const fresh = (await page.$$eval(CHAT_PLOT, (imgs) => imgs.map((i) => i.getAttribute("src"))))
    .filter((src) => !before.has(src));
  plotSrc = fresh.length ? fresh[fresh.length - 1] : null;
  const busy = await page.locator('[data-testid="agent-thinking"]').count();
  if (plotSrc && !busy) break;
  await page.waitForTimeout(500);
}
const seconds = Math.round((Date.now() - started) / 1000);

check("the Thinking indicator was on screen during the turn", sawThinking);
if (sawCount) {
  check("a wait past three seconds showed a running count", /\d+ s$/.test(lastCount), `last seen: ${lastCount}`);
} else {
  console.log("[INFO] every wait in this turn was under three seconds, so no count was due");
}
check("the reply put a plot in the chat", !!plotSrc, `after ${seconds} s`);

const plotIds = new Set();
if (plotSrc) {
  await page.waitForTimeout(1000);
  const loaded = await page.evaluate((src) => {
    const img = document.querySelector(`img[src="${src}"]`);
    return img ? { ok: img.complete && img.naturalWidth > 0, w: img.naturalWidth } : null;
  }, plotSrc);
  check("the plot image actually loads inline", !!loaded && loaded.ok, JSON.stringify(loaded));
  await page.screenshot({ path: path.join(outDir, "chat.png"), fullPage: false });

  const plotId = plotSrc.split("/api/plots/")[1].split("/")[0];
  plotIds.add(plotId);
  const record = await (await context.request.get(`${BASE_URL}/api/plots/${plotId}`, ORIGIN)).json();
  const spec = record.spec || {};
  check("the saved plot asks for value labels or annotations",
        !!spec.value_labels || (Array.isArray(spec.annotations) && spec.annotations.length > 0),
        JSON.stringify({ value_labels: spec.value_labels, annotations: spec.annotations }));
  const labels = Object.values(spec.x_labels || {}).join(" | ");
  check("the numbers are not stuffed into the x labels", !/\d\.\d\d/.test(labels), labels);
  const png = await context.request.get(`${BASE_URL}${plotSrc}`);
  fs.writeFileSync(path.join(outDir, "plot.png"), await png.body());
}

// The count itself. A fast model answers inside three seconds, as it did in
// the turn above, and then no count is due, so this holds the next message's
// POST in the browser for seven seconds. The chat marks a turn in progress the
// moment Enter is pressed (optimisticUserMessage), so this is the real waiting
// state with nothing about the component faked: only the network is slow.
await page.waitForTimeout(3000);
const HOLD_MS = 7000;
// Only the first POST is held, and the route is left in place rather than
// removed: unrouting while the held request is still inside its handler makes
// Playwright throw "Route is already handled" when the hold ends.
let held = false;
await page.route(`**/api/threads/${THREAD}/messages`, async (route) => {
  if (route.request().method() === "POST" && !held) {
    held = true;
    await new Promise((r) => setTimeout(r, HOLD_MS));
  }
  await route.continue();
});
await box.fill("Thanks. In one sentence, which method puts S1 lowest?");
await box.press("Enter");
let heldCount = "";
const heldStart = Date.now();
while (Date.now() - heldStart < HOLD_MS - 500) {
  const count = page.locator('[data-testid="agent-thinking-elapsed"]');
  if (await count.count()) {
    heldCount = (await count.first().innerText()).trim();
    if (parseInt(heldCount, 10) >= 5) {
      await page.locator('[data-testid="agent-thinking"]').screenshot({ path: path.join(outDir, "thinking-count.png") });
      break;
    }
  }
  await page.waitForTimeout(250);
}
check("a long wait shows 'Thinking...' with a running count of seconds",
      /^\d+ s$/.test(heldCount) && parseInt(heldCount, 10) >= 5, `last seen: "${heldCount}"`);
// Let that turn finish, so its reply is in the thread before cleanup reads it.
const finishBy = Date.now() + 3 * 60 * 1000;
await page.waitForTimeout(1500);
while (Date.now() < finishBy && await page.locator('[data-testid="agent-thinking"]').count()) {
  await page.waitForTimeout(500);
}
await page.screenshot({ path: path.join(outDir, "chat-final.png") });

const transcript = await page.locator("body").innerText();
check("no empty-reply fallback was needed", !transcript.includes("didn't manage to write a reply"));
console.log(`[INFO] images for a human look: ${outDir}`);

// Cleanup: the plots this turn drew (every PLOT_ARTIFACT marker in the
// thread's own messages, since the agent may draw more than one), then the
// thread. Nothing is deleted by listing: an admin's plot list includes other
// people's plots, and only ids this thread produced are ours to remove.
const state = await (await context.request.get(`${BASE_URL}/api/threads/${THREAD}/state`, ORIGIN))
  .json().catch(() => ({}));
for (const m of state.messages || []) {
  for (const hit of String(m.content || "").matchAll(/PLOT_ARTIFACT plot_id=(\w+)/g)) plotIds.add(hit[1]);
}
for (const id of plotIds) {
  const r = await context.request.delete(`${BASE_URL}/api/plots/${id}`, ORIGIN);
  console.log(`[cleanup] deleted plot ${id}: ${r.status()}`);
}
const t = await context.request.delete(`${BASE_URL}/api/threads/${THREAD}`, ORIGIN);
console.log(`[cleanup] deleted thread ${THREAD}: ${t.status()}`);
await browser.close();
summary();
