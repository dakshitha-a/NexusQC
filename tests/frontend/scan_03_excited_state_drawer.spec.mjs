/**
 * An excited-state scan's drawer chart draws one line per state.
 *
 * No frontend code changed for excited-state scans: P9.5 already gave
 * MiniLineChart a `series` array and ScanPlot already builds one series per
 * state out of `job.summary.state_energies_per_image`. So this is not a test
 * of new UI -- it is the check that the existing multi-series path actually
 * picks up the new data, which a code read cannot settle. ScanPlot has a
 * deliberate fallback to the single ground-state series when
 * state_energies_per_image is absent or in a shape it does not recognise, and
 * that fallback is exactly what a half-working backend change would land on:
 * one line, no legend, and nothing anywhere saying the other states went
 * missing.
 *
 * The scan is seeded through the API rather than by asking the agent, so a
 * failure here is about rendering rather than about model behaviour.
 *
 * Needs the docker-compose stack, and the image it runs must be current --
 * the ScanOrchestrator that fills state_energies_per_image lives in the api
 * container's own memory, so a stale image writes masters with its own older
 * normaliser even while the host checkout is up to date.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/scan_03_excited_state_drawer.spec.mjs
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

// One <path> per electronic state inside the scan chart's own SVG. Three is
// the count for the seeded scan (ground state plus two excited states); the
// single-series fallback would draw one.
const paths = page.locator("svg path[stroke-width='1.75']");
const nPaths = await paths.count();
check("the drawer chart draws one line per state, not a single fallback line",
      nPaths >= 3, `found ${nPaths} series paths`);

// The legend only renders when there is more than one series, so its presence
// is itself the multi-state signal, and the labels are what a chemist reads.
for (const label of ["Ground state", "State 1", "State 2"]) {
  check(`the legend names '${label}'`, await page.isVisible(`text=${label}`));
}

// The server-rendered PNG is still offered alongside the live chart -- it is
// what goes into a report, and P9.5 deliberately kept it rather than replacing
// it with the interactive version.
check("the server-rendered plot is still offered as a download",
      await page.isVisible("text=/Download.*plot|pes_plot/i").catch(() => false)
      || (await page.locator("a[download]").count()) > 0);

const ok = summary();
await browser.close();
process.exit(ok ? 0 : 1);
