/**
 * The orbital table's diffuseness column renders in a real browser.
 *
 * CLAUDE.md is explicit that a code read is not verification for frontend
 * work here, and this column is a good example of why: it is conditional on
 * `typeof r.diffuse_fraction === "number"`, so a backend that stopped
 * emitting the field, or emitted it as a string, would hide the whole column
 * while every unit-level check on the Python side still passed. The failure
 * would look exactly like a table that simply has no diffuseness to report.
 *
 * Finds its own subject rather than taking a job id: it walks /api/jobs
 * looking for a completed job whose orbital table already carries the
 * column, so it needs no seeding and creates nothing to clean up. If no such
 * job exists it says so and exits 0, since "no job has been run with a
 * diffuse-capable basis" is a state of the deployment rather than a failure
 * of the UI.
 *
 * Raw Playwright, chromium, headless, no @playwright/test runner, same as
 * every other spec here.
 *
 * Against the docker stack (needs `npm run build` first, see CLAUDE.md):
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/orbital_08_diffuse_column.spec.mjs
 *
 * Against a bare `python -m server.main` + `npm run dev` pair, where the
 * auth layer is inert and the login step is skipped automatically:
 *
 *   QC_AGENT_TEST_BASE_URL=http://localhost:5173 \
 *     node tests/frontend/orbital_08_diffuse_column.spec.mjs
 */
import { chromium } from "playwright";
import { BASE_URL, ADMIN_USER, adminPassword, LOGGED_IN } from "./_helpers.mjs";

const browser = await chromium.launch();
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
let failures = 0;
const check = (label, ok, detail = "") => {
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}${detail ? `  ${detail}` : ""}`);
  if (!ok) failures++;
};

await page.goto(BASE_URL, { waitUntil: "networkidle" });

// The bare dev pair has no database, so /api/auth/me 404s and there is
// nothing to log into. The stack requires it.
const authed = await page.evaluate(async () => (await fetch("/api/auth/me")).status !== 404);
if (authed) {
  await page.fill('input[name="username"], input[type="text"]', ADMIN_USER);
  await page.fill('input[type="password"]', adminPassword());
  await page.click('button[type="submit"]');
  await page.waitForSelector(LOGGED_IN, { timeout: 15000 });
}

const subject = await page.evaluate(async () => {
  const listed = await (await fetch("/api/jobs")).json();
  const jobs = Array.isArray(listed) ? listed : listed.jobs || [];
  for (const j of jobs) {
    const id = j.job_id || j.id;
    const full = await (await fetch(`/api/jobs/${id}`)).json();
    const rows = full?.summary?.orbital_table;
    if (rows?.length && typeof rows[0].diffuse_fraction === "number") {
      return { id, rows: rows.slice(0, 12), flagged: rows.filter((r) => r.diffuse).length };
    }
  }
  return null;
});

if (!subject) {
  console.log("No completed job carries a diffuseness column; nothing to check. Run one with a");
  console.log("diffuse basis (aug-cc-pVDZ) on PySCF or BAGEL and re-run.");
  await browser.close();
  process.exit(0);
}

console.log(`subject job: ${subject.id} (${subject.flagged} orbitals flagged diffuse in the API payload)`);
await page.locator(`text=${subject.id}`).first().click();
await page.waitForSelector('[data-testid^="orbital-row-"]', { timeout: 15000 });

const table = await page.evaluate(() => ({
  headers: [...document.querySelectorAll("th")].map((t) => t.textContent.trim()),
  rows: [...document.querySelectorAll('[data-testid^="orbital-row-"]')].map((tr) =>
    [...tr.querySelectorAll("td")].map((td) => td.textContent.trim()),
  ),
}));

const col = table.headers.indexOf("Diffuse");
check("the table has a Diffuse column", col >= 0, JSON.stringify(table.headers));
check("every rendered row shows a fraction",
      col >= 0 && table.rows.every((r) => /^\d\.\d{2}$/.test(r[col] ?? "")),
      col >= 0 ? `first: ${table.rows[0]?.[col]}` : "");
// The column is worth nothing if it only ever shows 0.00, which is what a
// silently-dropped field would look like if the header still rendered.
check("at least one row is above the flag threshold",
      col >= 0 && table.rows.some((r) => parseFloat(r[col]) > 0.5),
      col >= 0 ? `max ${Math.max(...table.rows.map((r) => parseFloat(r[col]) || 0)).toFixed(2)}` : "");
// A flagged orbital must not also be claiming an atom it does not sit on.
const localized = table.headers.indexOf("Localized on");
check("flagged rows report no atom localization",
      col >= 0 && localized >= 0 &&
        table.rows.filter((r) => parseFloat(r[col]) > 0.5).every((r) => /diffuse/.test(r[localized])),
      "");

console.log(failures ? `\nRESULT: ${failures} check(s) failed` : "\nRESULT: all checks passed");
await browser.close();
process.exit(failures ? 1 : 0);
