/**
 * The two destructive paths and the zip, in a real browser.
 *
 * "Delete this project" is genuinely ambiguous -- it can mean "I am done
 * with this grouping, put the jobs back" or "this study was a dead end,
 * take the results too" -- and guessing wrong in the second direction is
 * unrecoverable. So the dialog offers both with NEITHER preselected, and
 * that is the property this asserts first: not that the buttons exist, but
 * that nothing is armed or focused as a default answer.
 *
 * The download is checked by actually capturing the file and reading it
 * back, rather than by asserting a click happened. A download control that
 * fires a request and hands the browser something unreadable looks
 * identical from the outside.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/proj_02_delete_and_download.spec.mjs
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, openUserMenu, summary,
} from "./_helpers.mjs";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const DIALOG = '[data-testid="project-delete-dialog"]';

function seedJob(userId, label) {
  const code = `
import time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, write_meta
from app.auth.models import record_ownership

m = resolve_molecule("water")
spec = JobSpec(method="hf", engine="pyscf", task="single_point", subtype="gs",
               molecule=m.to_dict(), params={"basis": "sto-3g"})
job_id = get_job_manager().submit(spec)
for _ in range(90):
    if get_job_manager().status(job_id)["status"] in ("completed", "failed"):
        break
    time.sleep(1)
write_meta(job_id, {"label": ${JSON.stringify(label)}})
record_ownership("job", job_id, ${JSON.stringify(userId)})
print(job_id)
`;
  const out = execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code],
                           { cwd: REPO, encoding: "utf8", timeout: 180000 });
  return out.trim().split("\n").pop().trim();
}

/** The Projects section starts collapsed, matching Knowledge base and
 * Files either side of it, so every spec has to open it first. */
async function openProjects(page) {
  await page.waitForSelector('[data-testid="section-projects-toggle"]', { timeout: 15000 });
  if ((await page.locator('[data-testid="section-projects-panel"]').count()) === 0) {
    await page.click('[data-testid="section-projects-toggle"]');
    await page.waitForSelector('[data-testid="section-projects-panel"]', { timeout: 10000 });
  }
}

async function makeProject(page, name, jobIds) {
  const r = await page.request.post(`${BASE_URL}/api/projects`, {
    headers: { Origin: BASE_URL }, data: { name, job_ids: jobIds },
  });
  return (await r.json()).project_id;
}

const jobExists = async (page, id) =>
  (await page.request.get(`${BASE_URL}/api/jobs/${id}`)).status() === 200;

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_projdelete_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser, { acceptDownloads: true });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 200)));
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
  });

  const jobIds = [];
  const projectIds = [];
  try {
    console.log("\n== register + log in ==");
    await page.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
    await page.fill('input[placeholder="Email"]', `${username}@example.test`);
    await page.fill('input[placeholder="Username"]', username);
    await page.fill('input[placeholder="First name"]', "QA");
    await page.fill('input[placeholder="Last name"]', "Tester");
    await page.fill('input[placeholder="Password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 15000 });
    consoleErrors.length = 0;
    check("registered and logged in", true);

    const me = await (await page.request.get(`${BASE_URL}/api/auth/me`)).json();
    const a = seedJob(me.id, "qatest keeper");
    const b = seedJob(me.id, "qatest doomed");
    jobIds.push(a, b);
    const keepProject = await makeProject(page, "qatest keep these", [a]);
    const doomProject = await makeProject(page, "qatest delete these", [b]);
    projectIds.push(keepProject, doomProject);
    await page.reload({ waitUntil: "domcontentloaded" });
    await openProjects(page);
    await page.waitForSelector(`[data-testid="project-row-${keepProject}"]`, { timeout: 20000 });

    console.log("\n== the dialog offers both, with neither preselected ==");
    await page.locator(`[data-testid="project-row-${keepProject}"]`).hover();
    await page.click(`[data-testid="project-delete-${keepProject}"]`);
    await page.waitForSelector(DIALOG, { timeout: 10000 });
    check("the delete dialog renders", true);
    check("it names the project being deleted",
          (await page.locator(DIALOG).innerText()).includes("qatest keep these"));
    check("it says how many jobs are at stake",
          (await page.locator(DIALOG).innerText()).includes("1 job"),
          await page.locator(DIALOG).innerText());
    check("the keep-jobs option renders",
          await page.locator('[data-testid="project-delete-keep-jobs"]').isVisible());
    check("the delete-jobs option renders",
          await page.locator('[data-testid="project-delete-with-jobs"]').isVisible());
    check("the destructive option is DISABLED until the name is typed",
          await page.locator('[data-testid="project-delete-with-jobs"]').isDisabled(),
          "a preselected or immediately-clickable cascade is the failure this dialog exists to prevent");
    check("nothing is focused as a default answer",
          await page.evaluate(() => {
            const el = document.activeElement;
            if (!el) return true;
            const id = el.getAttribute("data-testid") || "";
            return id !== "project-delete-keep-jobs" && id !== "project-delete-with-jobs";
          }));
    check("a wrong phrase does not arm it", await (async () => {
      await page.fill('[data-testid="project-delete-phrase"]', "qatest keep");
      await page.waitForTimeout(150);
      return page.locator('[data-testid="project-delete-with-jobs"]').isDisabled();
    })());
    await page.click('[data-testid="project-delete-cancel"]');
    await page.waitForTimeout(300);
    check("cancelling closes it and deletes nothing",
          (await page.locator(DIALOG).count()) === 0
          && (await page.locator(`[data-testid="project-row-${keepProject}"]`).count()) === 1);

    console.log("\n== downloading a project ==");
    await page.locator(`[data-testid="project-row-${keepProject}"]`).hover();
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 30000 }),
      page.click(`[data-testid="project-download-${keepProject}"]`),
    ]);
    const name = download.suggestedFilename();
    check("the file is named after the project, not its id",
          /_archive\.zip$/.test(name) && name.includes("qatest_keep_these"), name);
    const path = await download.path();
    const bytes = readFileSync(path);
    check("it is a real zip", bytes.slice(0, 2).toString() === "PK", bytes.slice(0, 8).toString("hex"));
    // Read the central directory rather than pulling in a zip library: the
    // filenames are stored as plain bytes and that is all this needs.
    const text = bytes.toString("latin1");
    check("it carries a manifest", /_manifest\.csv/.test(text));
    check("and the job's own files", /jobs\/.*qatest_keeper/.test(text), text.slice(-400));

    console.log("\n== delete the project only ==");
    await page.locator(`[data-testid="project-row-${keepProject}"]`).hover();
    await page.click(`[data-testid="project-delete-${keepProject}"]`);
    await page.waitForSelector(DIALOG, { timeout: 10000 });
    await page.click('[data-testid="project-delete-keep-jobs"]');
    await page.waitForFunction(
      (id) => !document.querySelector(`[data-testid="project-row-${id}"]`),
      keepProject, { timeout: 15000 },
    );
    check("the project row is gone", true);
    check("but its job survives", await jobExists(page, a),
          "delete-project-only deleted the results, which is the one thing it must never do");
    await page.waitForFunction(
      (id) => document.querySelector(`[data-testid="jobmanager-row-${id}"]`),
      a, { timeout: 15000 },
    );
    check("and is back in the job manager unarchived", true);
    projectIds.splice(projectIds.indexOf(keepProject), 1);

    console.log("\n== delete the project and its jobs ==");
    await page.locator(`[data-testid="project-row-${doomProject}"]`).hover();
    await page.click(`[data-testid="project-delete-${doomProject}"]`);
    await page.waitForSelector(DIALOG, { timeout: 10000 });
    await page.fill('[data-testid="project-delete-phrase"]', "qatest delete these");
    await page.waitForTimeout(150);
    check("typing the exact name arms the destructive option",
          !(await page.locator('[data-testid="project-delete-with-jobs"]').isDisabled()));
    await page.click('[data-testid="project-delete-with-jobs"]');
    await page.waitForFunction(
      (id) => !document.querySelector(`[data-testid="project-row-${id}"]`),
      doomProject, { timeout: 20000 },
    );
    check("the project is gone", true);
    check("and so is its job, this time", !(await jobExists(page, b)));
    projectIds.splice(projectIds.indexOf(doomProject), 1);
    jobIds.splice(jobIds.indexOf(b), 1);

    console.log("\n== the danger zone's delete-all-projects ==");
    const survivor = await makeProject(page, "qatest survivor", [a]);
    projectIds.push(survivor);
    await openUserMenu(page);
    await page.click("text=Account");
    await page.waitForSelector('[data-testid="self-purge-projects"]', { timeout: 15000 });
    check("the account danger zone renders a delete-all-projects action", true);
    // The description is a sibling of the input/button row rather than an
    // ancestor of the button, so this reads the whole PurgeAction card.
    const purgeCard = page.locator('[data-testid="self-purge-projects"]')
      .locator("xpath=ancestor::div[contains(@class,'rounded')][1]");
    check("it explains what it takes and what it leaves",
          (await purgeCard.innerText()).includes("conversations")
          && (await purgeCard.innerText()).includes("no undo"),
          `the description must say the blast radius, since there is no undo -- card text: ${(await purgeCard.innerText()).slice(0, 160)}`);
    check("it is disabled until the phrase is typed",
          await page.locator('[data-testid="self-purge-projects"]').isDisabled());
    await page.fill('[data-testid="self-purge-projects-phrase"]', "DELETE MY PROJECTS");
    await page.waitForTimeout(150);
    await page.click('[data-testid="self-purge-projects"]');
    await page.waitForSelector('[data-testid="self-purge-projects-done"]', { timeout: 30000 });
    check("it reports what it deleted",
          (await page.locator('[data-testid="self-purge-projects-done"]').innerText()).includes("1 project"),
          await page.locator('[data-testid="self-purge-projects-done"]').innerText());
    check("the project is gone", !(await (async () => {
      const r = await page.request.get(`${BASE_URL}/api/projects/${survivor}`);
      return r.status() === 200;
    })()));
    check("and its job went with it, since this one cascades", !(await jobExists(page, a)));
    projectIds.splice(projectIds.indexOf(survivor), 1);
    jobIds.splice(jobIds.indexOf(a), 1);

    check("no console or page errors during the whole run",
          consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
  } catch (err) {
    check("the run completed without throwing", false, String(err).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 900));
    } catch {}
  } finally {
    for (const id of projectIds) {
      try {
        await page.request.delete(`${BASE_URL}/api/projects/${id}?delete_jobs=false`,
                                  { headers: { Origin: BASE_URL } });
      } catch {}
    }
    for (const id of jobIds) {
      try {
        await page.request.delete(`${BASE_URL}/api/jobs/${id}`, { headers: { Origin: BASE_URL } });
      } catch {}
    }
    await deleteUserByUsername(adminCtx, username);
    await browser.close();
  }

  process.exit(summary() ? 0 : 1);
}

main();
