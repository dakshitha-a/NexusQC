/**
 * The admin console's "Cores per calculation" field, in a real browser.
 *
 * tests/backend/conf_06_cores_per_job.py proves a stored value reaches the
 * job. This proves the console can store one: the field renders in the
 * Overview section with the live value and a note saying where it comes
 * from, a new value saves through the Save button and survives a reload,
 * and the Save button stays disabled for a value above the ceiling or a
 * fraction. The setting is restored to what it was before, through the API,
 * even if a check fails.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/admin_02_cores_per_job.spec.mjs
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  newBrowser, newContext, adminApiLogin, openUserMenu, check, summary, BASE_URL, LOGGED_IN,
} from "./_helpers.mjs";

const ORIGIN = { headers: { Origin: BASE_URL } };
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "admin02-"));
const browser = await newBrowser();
const context = await newContext(browser);
await adminApiLogin(context);
const before = await (await context.request.get(`${BASE_URL}/api/admin/config`, ORIGIN)).json();
const original = before.cores_per_job_source === "setting" ? before.cores_per_job : null;
const target = before.cores_per_job === 3 ? 2 : 3;

async function openOverview(page) {
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await openUserMenu(page);
  await page.locator('[data-testid="admin-open"]').click();
  await page.waitForSelector("text=Admin console", { timeout: 10000 });
  const nav = page.locator('[data-testid="admin-nav-overview"]');
  if (await nav.count()) await nav.click();
  await page.waitForSelector('[data-testid="admin-cores-per-job"]', { timeout: 10000 });
  return page.locator('[data-testid="admin-cores-per-job"]');
}

try {
  const page = await context.newPage();
  let field = await openOverview(page);
  check("the Cores per calculation field renders in the admin Overview", await field.count() === 1);
  const text = await field.innerText();
  check("it is labelled for a chemist and says what each engine does with it",
        text.includes("Cores per calculation") && text.includes("ORCA") && text.includes("threads"), text);
  const input = field.locator('input[type="number"]');
  check("it shows the live value", (await input.inputValue()) === String(before.cores_per_job),
        `${await input.inputValue()} vs ${before.cores_per_job}`);
  const save = field.locator('button:has-text("Save")');

  await input.fill(String(before.cores_per_job_ceiling + 1));
  check("Save is disabled above the ceiling", await save.isDisabled());
  await input.fill("2.5");
  check("Save is disabled for a fraction", await save.isDisabled());

  await input.fill(String(target));
  check("Save is enabled for a whole number in range", await save.isEnabled());
  await save.click();
  await page.waitForTimeout(1200);
  await field.screenshot({ path: path.join(outDir, "field-saved.png") });

  field = await openOverview(page);
  check("the new value survives a reload",
        (await field.locator('input[type="number"]').inputValue()) === String(target));
  check("after saving, the note says it was set here", (await field.innerText()).includes("Set here"),
        await field.innerText());
  const after = await (await context.request.get(`${BASE_URL}/api/admin/config`, ORIGIN)).json();
  check("the server holds it", after.cores_per_job === target && after.cores_per_job_source === "setting",
        JSON.stringify({ v: after.cores_per_job, s: after.cores_per_job_source }));
  console.log(`[INFO] screenshot for a human look: ${outDir}`);
} finally {
  const r = await context.request.patch(`${BASE_URL}/api/admin/config`,
    { ...ORIGIN, data: { key: "cores_per_job", value: original } });
  console.log(`[cleanup] restored cores_per_job to ${original === null ? "the .env default" : original}: ${r.status()}`);
  await browser.close();
}
summary();
