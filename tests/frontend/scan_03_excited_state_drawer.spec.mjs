/**
 * An excited-state scan's drawer shows every state's curve.
 *
 * Which view that is depends on whether the scan has finished. While images
 * are still running there is no server-rendered plot yet, so ScanPlot draws
 * the live MiniLineChart from `job.summary.state_energies_per_image`; once
 * every image is terminal, ScanOrchestrator renders `artifacts.pes_plot` and
 * the drawer shows that PNG instead (699c70a). This spec checks both, because
 * both are real states of the same panel and the earlier version of this file
 * only knew about the first one -- it asserted on the mini chart against a
 * FINISHED scan, which passed only for as long as the PNG was download-only.
 *
 * The fallback half is forced rather than raced: aborting the request for the
 * pes_plot artifact trips ScanPlot's own onError path, which is exactly what
 * puts the mini chart back on screen. That makes the multi-series check
 * deterministic instead of depending on catching a scan mid-flight.
 *
 * What the mini chart is worth checking for at all: ScanPlot has a deliberate
 * fallback to a single ground-state series when state_energies_per_image is
 * absent or in a shape it does not recognise, and that fallback is what a
 * half-working backend change lands on -- one line, no legend, and nothing
 * anywhere saying the other states went missing.
 *
 * The scan is seeded through the API rather than by asking the agent, so a
 * failure here is about rendering rather than about model behaviour.
 *
 * Needs the docker-compose stack, and the image it runs must be current --
 * the ScanOrchestrator that fills state_energies_per_image lives in the api
 * container's own memory, so a stale image writes masters with its own older
 * normaliser even while the host checkout is up to date. The frontend it
 * drives is whatever is in frontend/dist, so `npm run build` first if the
 * drawer is what changed.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 QC_AGENT_TEST_SCAN_JOB_ID=<id> \
 *     node tests/frontend/scan_03_excited_state_drawer.spec.mjs
 */
import { newBrowser, newContext, adminApiLogin, check, summary, BASE_URL, LOGGED_IN } from "./_helpers.mjs";

const SCAN_JOB_ID = process.env.QC_AGENT_TEST_SCAN_JOB_ID;
if (!SCAN_JOB_ID) {
  console.error("Set QC_AGENT_TEST_SCAN_JOB_ID to a completed interp_pes/ee job id.");
  console.error("tests/backend/scan_02_excited_state_scans.py leaves several behind.");
  process.exit(2);
}

const browser = await newBrowser();
const context = await newContext(browser);
await adminApiLogin(context);
const page = await context.newPage();
await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });

// The job list, then the job itself. Rows are addressed by job id rather
// than by the label they display, which is not unique across two scans of
// the same molecule at the same level of theory.
const row = page.locator(`[data-testid="jobmanager-row-${SCAN_JOB_ID}"]`);
await row.waitFor({ timeout: 20000 }).catch(() => {});
check("the seeded scan has a row in the Job Manager", (await row.count()) > 0,
      `job ${SCAN_JOB_ID}`);
// dispatchEvent rather than click(): the dock's collapsible section headers
// are sticky, and one of them sits over the row's centre point, so a real
// mouse click is intercepted no matter how the row is scrolled. React
// attaches its listeners at the root, so a dispatched click still runs the
// row's own onClick.
await row.scrollIntoViewIfNeeded().catch(() => {});
await row.dispatchEvent("click");
await page.waitForSelector("text=PES plot", { timeout: 15000 });

// --- the finished scan: the server-rendered plot IS the preview ---------
const plotImg = page.locator('img[src*="pes_plot"]');
check("a finished scan's preview shows the server-rendered PES plot",
      (await plotImg.count()) > 0);
const loaded = (await plotImg.count())
  ? await plotImg.first().evaluate((el) => ({ nw: el.naturalWidth, nh: el.naturalHeight }))
  : { nw: 0, nh: 0 };
check("that plot actually loaded rather than 404ing", loaded.nw > 100 && loaded.nh > 100,
      JSON.stringify(loaded));
check("the mini chart is not drawn underneath it as well",
      (await page.locator("svg path[stroke-width='1.75']").count()) === 0);

// The server-rendered PNG is still offered as a download -- it is what goes
// into a report, and showing it inline did not replace that.
check("the plot is still offered as a download",
      (await page.locator("a[download]").count()) > 0);

// --- the live view: one line per state, no PNG available ----------------
// Aborting the artifact request is the same condition a still-running scan
// is in from ScanPlot's point of view: no usable PNG, so fall back.
await page.route(`**/api/jobs/${SCAN_JOB_ID}/artifacts/pes_plot`, (route) => route.abort());
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
const rowAgain = page.locator(`[data-testid="jobmanager-row-${SCAN_JOB_ID}"]`);
await rowAgain.waitFor({ timeout: 20000 });
await rowAgain.scrollIntoViewIfNeeded().catch(() => {});
await rowAgain.dispatchEvent("click");
await page.waitForSelector("text=PES plot", { timeout: 15000 });

// One <path> per electronic state inside the scan chart's own SVG. Three is
// the count for the seeded scan (ground state plus two excited states); the
// single-series fallback would draw one.
const paths = page.locator("svg path[stroke-width='1.75']");
const nPaths = await paths.count();
check("with no PNG to show, the chart draws one line per state, not a single fallback line",
      nPaths >= 3, `found ${nPaths} series paths`);

// The legend only renders when there is more than one series, so its presence
// is itself the multi-state signal, and the labels are what a chemist reads.
// Spectroscopic notation since R-096: the legend used to say "Ground state",
// "State 1", "State 2", which collides with target_states' own 1-based
// numbering where state 1 IS the ground state.
for (const label of ["S0", "S1", "S2"]) {
  check(`the legend names '${label}'`, await page.isVisible(`text=${label}`));
}

const ok = summary();
await browser.close();
process.exit(ok ? 0 : 1);
