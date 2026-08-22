/**
 * The Plots panel, driven in a real browser.
 *
 * A code read cannot confirm any of this: whether the section actually
 * appears in the dock, whether a thumbnail's <img> really loads from the
 * plots route (as opposed to rendering a broken-image box), whether the
 * two-click delete works, or whether attaching puts a chip in the composer.
 * Several real bugs in this repo showed up only under real interaction --
 * see docs/ARCHITECTURE.md's note on the Strict Mode WebGL leak.
 *
 * Needs the docker-compose stack and a plot already saved; the plot is
 * created through the API here rather than by asking the agent, so the check
 * is about the panel rather than about model behaviour (which
 * tests/e2e/e2e_09_plot_tools.py covers).
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/plots_01_panel.spec.mjs
 */
import { newBrowser, newContext, adminApiLogin, check, summary, BASE_URL, LOGGED_IN } from "./_helpers.mjs";

const browser = await newBrowser();
const context = await newContext(browser);
await adminApiLogin(context);
const page = await context.newPage();
await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });

// The section header itself.
const header = page.locator('text="Plots"').first();
check("the Plots section is present in the instrument panel", await header.count() > 0);

// Expand it only if it is actually collapsed. Clicking unconditionally
// toggles an already-open section shut, which reads as "the panel lists no
// plots" and is a bug in the test rather than in the panel.
const rows = page.locator('[data-testid^="plot-label-"]');
await page.waitForTimeout(1200);
if ((await rows.count()) === 0) {
  await header.click().catch(() => {});
  await page.waitForTimeout(1200);
}
const n = await rows.count();
check("the panel lists at least one saved plot", n > 0, `found ${n}`);

if (n > 0) {
  const plotId = (await rows.first().getAttribute("data-testid")).replace("plot-label-", "");

  // A thumbnail that renders is the whole point -- naturalWidth is what
  // distinguishes a loaded image from a broken-image placeholder, which
  // looks identical to a screenshot-based check.
  const loaded = await page.evaluate(() => {
    const img = document.querySelector('img[src*="/api/plots/"]');
    return img ? { ok: img.complete && img.naturalWidth > 0, w: img.naturalWidth } : null;
  });
  check("a plot thumbnail actually loads from the plots route",
        !!loaded && loaded.ok, JSON.stringify(loaded));

  check("the row offers a download button", await page.locator(`[data-testid="plot-download-${plotId}"]`).count() > 0);
  check("the row offers a delete button", await page.locator(`[data-testid="plot-delete-${plotId}"]`).count() > 0);

  // Delete is two-click, like a job's: the first click must only arm it.
  await page.click(`[data-testid="plot-delete-${plotId}"]`);
  await page.waitForTimeout(300);
  check("deleting is a two-step confirm, not immediate",
        await page.locator(`[data-testid="plot-delete-confirm-${plotId}"]`).count() > 0);
  await page.click(`[data-testid="plot-delete-dismiss-${plotId}"]`);
  await page.waitForTimeout(300);
  check("dismissing the confirm leaves the plot in place",
        await page.locator(`[data-testid="plot-label-${plotId}"]`).count() > 0);

  // One filter for the drawer, not one find bar per row. The row label used
  // to render through SearchableText, a document viewer that carries its own
  // find bar, so every plot grew a search box of its own.
  check("there is exactly one filter control for the whole drawer",
        (await page.locator('[data-testid="plots-filter"]').count()) === 1);
  await page.fill('[data-testid="plots-filter"]', "zzz-matches-nothing");
  await page.waitForTimeout(300);
  check("filtering hides non-matching rows",
        (await page.locator('[data-testid^="plot-label-"]').count()) === 0);
  await page.click('[data-testid="plots-filter-clear"]');
  await page.waitForTimeout(300);
  check("clearing the filter brings them back",
        (await page.locator('[data-testid^="plot-label-"]').count()) > 0);

  // Clicking a row enlarges the plot, the way a job row opens its drawer.
  await page.click(`[data-testid="plot-row-${plotId}"]`);
  await page.waitForTimeout(700);
  const enlarged = await page.evaluate(() => {
    const img = document.querySelector('[data-testid="plot-flyout-image"]');
    return img ? { ok: img.complete && img.naturalWidth > 0, w: img.clientWidth } : null;
  });
  check("clicking a row opens a flyout with the plot enlarged",
        !!enlarged && enlarged.ok, JSON.stringify(enlarged));
  const thumbWidth = await page.evaluate(() => {
    const t = document.querySelector('img[src*="/api/plots/"]');
    return t ? t.clientWidth : 0;
  });
  check("the flyout image is genuinely larger than the row thumbnail",
        !!enlarged && enlarged.w > thumbWidth, `flyout=${enlarged?.w} thumb=${thumbWidth}`);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  check("Escape closes the flyout",
        (await page.locator('[data-testid="plot-flyout-image"]').count()) === 0);

  // Attaching puts a chip in the composer, which is what makes a plot
  // askable and editable without the user quoting its id.
  await page.click(`[data-testid="plot-select-${plotId}"]`);
  await page.waitForTimeout(200);
  await page.click('button:has-text("Attach to prompt")');
  await page.waitForTimeout(400);
  check("attaching a plot puts a chip in the composer",
        await page.locator(`[data-testid="composer-detach-plot-${plotId}"]`).count() > 0);
}

// A spectrum's PNG now lives in the plot store while still being registered
// under the artifact key the job drawer's own panels fetch it by. That second
// name only works because the artifact route's containment check allows the
// plot store as a second root, and nothing above this line would notice if it
// did not -- the panel test never opens a drawer. So check the route directly,
// for whatever spectrum artifacts the account actually has.
const artifactStatuses = await page.evaluate(async () => {
  const jobs = await (await fetch("/api/jobs")).json();
  const out = [];
  for (const row of (jobs.jobs ?? jobs).slice(0, 25)) {
    const job = await (await fetch(`/api/jobs/${row.job_id}`)).json();
    for (const key of ["uvvis_spectrum", "ir_spectrum", "ensemble_spectrum"]) {
      if (job.artifacts && job.artifacts[key]) {
        const r = await fetch(`/api/jobs/${row.job_id}/artifacts/${key}`);
        out.push({ key, status: r.status });
      }
    }
  }
  return out;
});
if (artifactStatuses.length === 0) {
  console.log("[SKIP] no job in this account has a spectrum artifact to check the drawer's fetch path with");
} else {
  check("spectrum artifacts still serve through the job artifact route",
        artifactStatuses.every((a) => a.status === 200), JSON.stringify(artifactStatuses));
}

const ok = summary();
await browser.close();
process.exit(ok ? 0 : 1);
