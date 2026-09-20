/**
 * The orbital table marks the active window, shows what each active orbital
 * started as, and puts the rotation warning above the numbers, in a real
 * browser.
 *
 * These are the three pieces of the active-space record a CASSCF-family
 * result carries (app/chemistry/jobs/active_space.py): `active` on every
 * row, `reference_index`/`reference_weight` on the active rows when the run
 * could be compared with the orbitals it started from, and
 * `active_space_warning` when the optimizer rotated a requested orbital out.
 * Each is conditional in OrbitalTable.tsx, so a backend that stopped
 * emitting a field would hide the mark, the column or the warning while
 * every Python check still passed. Same reasoning as orbital_08.
 *
 * Finds a completed job whose table already carries `active`, and otherwise
 * serves a recorded payload through page.route: the rows are the converged
 * table of a water/6-31G CASSCF(4,4) that was asked for the source's rows
 * [4, 5, 7, 8] and rotated row 4 out (tests/backend/
 * active_02_recorded_active_space.py, job B), trimmed to what the
 * assertions read.
 *
 * Writes a screenshot of the table to docs/e2e-artifacts/ (gitignored, the
 * place this repository keeps machine-made screenshots) so the marks can be
 * looked at, not only asserted on.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/orbital_09_active_space_marks.spec.mjs
 */
import { mkdirSync } from "node:fs";
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
    const usable = rows?.length && rows.some((r) => r.active) && full.summary.active_space_warning
      && rows.some((r) => typeof r.reference_index === "number");
    if (usable) return { id, window: full.summary.active_orbital_window };
  }
  return null;
});

const RECORDED = {
  active_orbital_window: [4, 5, 6, 7],
  active_space_orbital_indices: [4, 5, 7, 8],
  initial_orbitals_source_job_id: "a1b2c3d4e5f6",
  reference_orbital_weights: { 4: 0.0, 5: 0.6693, 7: 0.1137, 8: 0.4833 },
  active_space_warning:
    "The optimizer did not keep the active space it started from. Against job a1b2c3d4e5f6's "
    + "orbital table: orbital 4 kept weight 0.00; orbital 7 kept weight 0.11; orbital 8 kept weight 0.48 "
    + "in the converged active space, so it was rotated out. The energies are those of the converged "
    + "space, not the requested one.",
  orbital_table: [
    { index: 1, spin: null, energy_eV: -559.52, occupancy: 2.0, character: "n", localized_atom: "O1", active: false },
    { index: 2, spin: null, energy_eV: -36.77, occupancy: 2.0, character: "n", localized_atom: "O1", active: false },
    { index: 3, spin: null, energy_eV: -19.13, occupancy: 2.0, character: "sigma", localized_atom: "O1-H2", active: false },
    { index: 4, spin: null, energy_eV: -13.66, occupancy: 1.9996, character: "n", localized_atom: "O1", active: true, reference_index: 5, reference_weight: 0.6693 },
    { index: 5, spin: null, energy_eV: -15.30, occupancy: 1.9970, character: "n", localized_atom: "O1", active: true, reference_index: 8, reference_weight: 0.4833 },
    { index: 6, spin: null, energy_eV: 18.13, occupancy: 0.0032, character: "sigma*", localized_atom: "O1-H2", active: true, reference_index: 7, reference_weight: 0.1137 },
    { index: 7, spin: null, energy_eV: 32.68, occupancy: 0.0002, character: "n", localized_atom: "H2", active: true, reference_index: 4, reference_weight: 0.0 },
    { index: 8, spin: null, energy_eV: 5.47, occupancy: 0.0, character: "sigma*", localized_atom: "O1-H3", active: false },
    { index: 9, spin: null, energy_eV: 23.24, occupancy: 0.0, character: "sigma*", localized_atom: "O1-H2", active: false },
  ],
};

if (!subject) {
  stubbed = true;
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
  subject = { id: listed, window: RECORDED.active_orbital_window };
  await page.route(`**/api/jobs/${listed}`, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.summary = { ...(body.summary || {}), ...RECORDED };
    await route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  await page.reload({ waitUntil: "networkidle" });
}

console.log(`subject job: ${subject.id}${stubbed ? " (recorded payload; no live job carries the record yet)" : ""}`);
// The job manager's own row, by test id: the id also appears in conversation
// text ("Started ... Job id ...") and a text= locator can land there instead.
await page.locator(`[data-testid="jobmanager-row-${subject.id}"]`).first().click();
await page.waitForSelector('[data-testid^="orbital-row-"]', { timeout: 15000 });

const seen = await page.evaluate(() => {
  const el = document.querySelector('[data-testid^="orbital-row-"]')?.closest("table");
  const container = el?.closest("div.flex.min-h-0.flex-col");
  const rows = [...(el?.querySelectorAll('[data-testid^="orbital-row-"]') ?? [])];
  return {
    headers: [...(el?.querySelectorAll("th") ?? [])].map((t) => t.textContent.trim()),
    activeRows: rows.filter((tr) => tr.dataset.active === "true").map((tr) => tr.dataset.testid),
    hairlined: rows.filter((tr) => tr.querySelector("td.hairline")).map((tr) => tr.dataset.testid),
    titled: rows.filter((tr) => tr.querySelector('td[title="In the active space"]')).length,
    fromCells: rows.map((tr) => {
      const tds = [...tr.querySelectorAll("td")];
      return tds[tds.length - 1].textContent.trim();
    }),
    note: container?.querySelector('[data-testid="orbital-active-note"]')?.textContent ?? "",
    warning: container?.querySelector('[data-testid="orbital-active-warning"]')?.textContent ?? "",
  };
});

const want = subject.window.map((i) => `orbital-row-${i}`);
check("exactly the window rows are marked active", JSON.stringify(seen.activeRows) === JSON.stringify(want),
      JSON.stringify(seen.activeRows));
check("each of them carries the hairline on its index cell", JSON.stringify(seen.hairlined) === JSON.stringify(want));
check("and say so on hover", seen.titled === want.length, `${seen.titled} titled`);
check("the table has a From column", seen.headers.includes("From"), JSON.stringify(seen.headers));
const fromCol = seen.headers.indexOf("From");
check("active rows show the reference orbital and its weight, other rows show none",
      fromCol >= 0 && seen.fromCells.some((c) => /^#\d+ · \d\.\d{2}$/.test(c))
        && seen.fromCells.filter((c) => c === "--").length > 0,
      JSON.stringify(seen.fromCells));
check("the header line names the active window and the reference table",
      /active space: rows \d+ to \d+/.test(seen.note) && /named as .* in job .*'s table/.test(seen.note), seen.note);
check("the warning is shown above the table", /did not keep the active space/.test(seen.warning),
      seen.warning.slice(0, 80));

mkdirSync(new URL("../../docs/e2e-artifacts/", import.meta.url), { recursive: true });
const shot = new URL("../../docs/e2e-artifacts/orbital_09_active_space_marks.png", import.meta.url).pathname;
const tableEl = await page.locator('[data-testid^="orbital-row-"]').first().locator("xpath=ancestor::div[contains(@class,'min-h-0')][1]");
await tableEl.screenshot({ path: shot });
await page.screenshot({ path: shot.replace(".png", "_page.png") });
console.log(`screenshot: ${shot}`);

console.log(failures ? `\nRESULT: ${failures} check(s) failed` : "\nRESULT: all checks passed");
await browser.close();
process.exit(failures ? 1 : 0);
