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
 * looking for a completed job whose orbital table already carries the column,
 * so it needs no seeding and creates nothing to clean up.
 *
 * When no such job exists it does NOT skip. There is no route that creates a
 * job directly (they come from the agent's draft/approve flow), and a spec
 * that quietly passes whenever the deployment happens to have no
 * aug-cc-pVDZ run would be a permanent no-op wearing a green tick -- which is
 * exactly what happened the first time this was written. It falls back to
 * serving a recorded payload through page.route instead. That still drives
 * the real component in a real browser, which is the thing a code read
 * cannot substitute for; only the arrival of the data is stubbed.
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

let stubbed = false;
let subject = await page.evaluate(async () => {
  const listed = await (await fetch("/api/jobs")).json();
  const jobs = Array.isArray(listed) ? listed : listed.jobs || [];
  for (const j of jobs) {
    const id = j.job_id || j.id;
    const full = await (await fetch(`/api/jobs/${id}`)).json();
    const rows = full?.summary?.orbital_table;
    // Carrying the column is not the same as having anything in it. This
    // accepted any job whose table had a `diffuse_fraction` field, so a job in
    // a basis with no diffuse functions was picked as the subject and the
    // assertion below could not pass: the README's own worked example says
    // water in cc-pVDZ produces nothing above 0.22 while aug-cc-pVDZ finds
    // five orbitals between 0.63 and 0.94. That is the correct answer for
    // cc-pVDZ, not a failure, and the stub further down exists precisely for
    // when no suitable job is on the stack. It was never reached because
    // nothing rejected an unsuitable one.
    //
    // The odds of picking wrongly went up on 2026-09-06, when optimization and
    // frequency jobs started carrying orbital tables too, so there are more
    // candidates and most of them are in whatever basis the job used.
    const usable = rows?.length
      && typeof rows[0].diffuse_fraction === "number"
      && rows.some((r) => r.diffuse);
    if (usable) {
      return { id, rows: rows.slice(0, 12), flagged: rows.filter((r) => r.diffuse).length };
    }
  }
  return null;
});

if (!subject) {
  // Recorded from a real water/aug-cc-pVDZ HF run through run_single_point,
  // trimmed to the rows the assertions below read.
  stubbed = true;
  const rows = [
    { index: 1, spin: null, energy_eV: -559.996, occupancy: 2, character: "n",
      localized_atom: "O1", diffuse_fraction: 0.0, diffuse: false },
    { index: 5, spin: null, energy_eV: -13.841, occupancy: 2, character: "n",
      localized_atom: "O1", diffuse_fraction: 0.0, diffuse: false },
    { index: 6, spin: null, energy_eV: 0.958, occupancy: 0, character: "sigma*",
      localized_atom: "diffuse, mostly outside the molecule", diffuse_fraction: 0.82, diffuse: true },
    { index: 7, spin: null, energy_eV: 1.576, occupancy: 0, character: "sigma*",
      localized_atom: "diffuse, mostly outside the molecule", diffuse_fraction: 0.94, diffuse: true },
    { index: 10, spin: null, energy_eV: 6.036, occupancy: 0, character: "n",
      localized_atom: "O1", diffuse_fraction: 0.42, diffuse: false },
  ];
  const listed = await page.evaluate(async () => {
    const r = await (await fetch("/api/jobs")).json();
    const jobs = Array.isArray(r) ? r : r.jobs || [];
    return jobs.length ? jobs[0].job_id || jobs[0].id : null;
  });
  if (!listed) {
    console.log("FAIL: no jobs at all in this deployment, so there is nothing to open the drawer on.");
    await browser.close();
    process.exit(1);
  }
  subject = { id: listed, rows, flagged: 2 };
  await page.route(`**/api/jobs/${listed}`, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.summary = { ...(body.summary || {}), orbital_table: rows };
    await route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  await page.reload({ waitUntil: "networkidle" });
}

console.log(`subject job: ${subject.id}${stubbed ? " (recorded payload; no live job carries the column)" : ""}`
            + ` -- ${subject.flagged} orbitals flagged diffuse in the payload`);
await page.locator(`text=${subject.id}`).first().click();
await page.waitForSelector('[data-testid^="orbital-row-"]', { timeout: 15000 });

// Scoped to the table the orbital rows live in. The drawer can render a
// second table above it (an excited-state job shows one), and a bare
// querySelectorAll("th") merges both header rows, which silently shifts every
// column index and was enough to make two assertions read the wrong cell.
const table = await page.evaluate(() => {
  const el = document.querySelector('[data-testid^="orbital-row-"]')?.closest("table");
  if (!el) return { headers: [], rows: [] };
  return {
    headers: [...el.querySelectorAll("th")].map((t) => t.textContent.trim()),
    rows: [...el.querySelectorAll('[data-testid^="orbital-row-"]')].map((tr) =>
      [...tr.querySelectorAll("td")].map((td) => td.textContent.trim()),
    ),
  };
});

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
const flaggedRows = col >= 0 ? table.rows.filter((r) => parseFloat(r[col]) > 0.5) : [];
check("flagged rows report no atom localization",
      localized >= 0 && flaggedRows.length > 0 &&
        flaggedRows.every((r) => /diffuse/.test(r[localized])),
      `${flaggedRows.length} flagged row(s)`);

console.log(failures ? `\nRESULT: ${failures} check(s) failed` : "\nRESULT: all checks passed");
await browser.close();
process.exit(failures ? 1 : 0);
