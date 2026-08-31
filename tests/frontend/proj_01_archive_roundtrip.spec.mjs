/**
 * The whole project-archive story, driven end to end in a real browser:
 * select jobs, file them into a project, watch them leave the job manager,
 * find them again, and send them back.
 *
 * Every new piece of UI is asserted to actually RENDER before anything is
 * asserted about what clicking it does. That is not belt and braces: each
 * left-rail section sits inside its own PanelErrorBoundary, so a component
 * that throws leaves a working-looking app with one quiet fallback in the
 * rail, and a test that only clicks through the happy path would never
 * look at it. Console errors and page errors are collected throughout and
 * a non-empty collection is itself a failed check, so a render that only
 * half broke is caught too.
 *
 * Jobs are seeded through the container rather than through the chat: this
 * needs three completed jobs and none of it is testing the agent, so three
 * LLM turns would add ten minutes to prove nothing. Same in-container exec
 * shape tests/backend/proj_02_lifecycle.py uses.
 *
 * Raw Playwright, chromium, headless -- no @playwright/test runner, same
 * convention as the rest of tests/frontend.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/proj_01_archive_roundtrip.spec.mjs
 */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, summary,
} from "./_helpers.mjs";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

const SHOW_ARCHIVED = '[data-testid="jobmanager-show-archived"]';
const ADD_TO_PROJECT = '[data-testid="jobmanager-add-to-project"]';
const POPOVER = '[data-testid="add-to-project-popover"]';
const PROJECTS_PANEL = '[data-testid="section-projects-panel"]';

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

const rowCount = (page) => page.locator('[data-testid^="jobmanager-row-"]').count();
const row = (page, id) => page.locator(`[data-testid="jobmanager-row-${id}"]`);

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_projroundtrip_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();

  // A render that throws inside a boundary is otherwise silent.
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
    check("registered and logged in", true);
    // Collected from here rather than from page.goto: the app probes
    // /api/auth/me on load and a visitor who is not logged in yet gets a
    // 401, which the browser logs as a console error. That one is expected
    // and says nothing about this feature; anything after login does.
    consoleErrors.length = 0;

    const me = await (await page.request.get(`${BASE_URL}/api/auth/me`)).json();

    console.log("\n== the Projects section renders, empty ==");
    await page.waitForSelector('[data-testid="section-projects-toggle"]', { timeout: 15000 });
    check("the left rail has a Projects section", true);
    check("it starts collapsed, like Knowledge base and Files",
          (await page.locator('[data-testid="section-projects-panel"]').count()) === 0);
    await openProjects(page);
    check("its header reads Projects",
          (await page.locator('[data-testid="section-projects-toggle"]').innerText()).toUpperCase().includes("PROJECTS"));
    check("the section body renders", await page.locator(PROJECTS_PANEL).isVisible());
    await page.waitForSelector('[data-testid="projects-empty"]', { timeout: 10000 });
    check("an empty archive explains how to fill it",
          (await page.locator('[data-testid="projects-empty"]').innerText()).includes("Add to project"));
    check("there is a control for making a new project",
          await page.locator('[data-testid="project-add-toggle"]').isVisible());

    console.log("\n== seed three jobs ==");
    const a = seedJob(me.id, "qatest alpha");
    const b = seedJob(me.id, "qatest bravo");
    const c = seedJob(me.id, "qatest charlie");
    jobIds.push(a, b, c);
    await page.waitForFunction(
      (ids) => ids.every((id) => document.querySelector(`[data-testid="jobmanager-row-${id}"]`)),
      [a, b, c], { timeout: 30000 },
    );
    check("all three are listed in the job manager", (await rowCount(page)) >= 3);

    console.log("\n== the selection bar offers Add to project ==");
    await row(page, a).locator('input[type="checkbox"]').check();
    await row(page, b).locator('input[type="checkbox"]').check();
    await page.waitForSelector(ADD_TO_PROJECT, { timeout: 10000 });
    check("the selection bar says how many are selected",
          (await page.locator("text=2 selected").count()) > 0);
    check("Add to project renders", await page.locator(ADD_TO_PROJECT).isVisible());
    check("and Attach to prompt is still there beside it, not replaced",
          await page.locator('[data-testid="jobmanager-attach-to-prompt"]').isVisible());

    console.log("\n== filing them into a new project ==");
    await page.click(ADD_TO_PROJECT);
    await page.waitForSelector(POPOVER, { timeout: 10000 });
    check("the popover renders", true);
    check("it says what is about to happen",
          (await page.locator(POPOVER).innerText()).includes("File 2 jobs"));
    await page.fill('[data-testid="add-to-project-new-name"]', "qatest study one");
    await page.click('[data-testid="add-to-project-create"]');

    await page.waitForFunction(
      (id) => !document.querySelector(`[data-testid="jobmanager-row-${id}"]`),
      a, { timeout: 15000 },
    );
    check("an archived job leaves the job manager", (await row(page, a).count()) === 0);
    check("and so does the other one", (await row(page, b).count()) === 0);
    check("the unarchived one stays", (await row(page, c).count()) === 1);

    await page.waitForSelector('[data-testid^="project-row-"]', { timeout: 15000 });
    const projectRow = page.locator('[data-testid^="project-row-"]').first();
    const projectId = (await projectRow.getAttribute("data-testid")).replace("project-row-", "");
    projectIds.push(projectId);
    check("the project renders in the rail with its name and count",
          /qatest study one/.test(await projectRow.innerText())
          && /2 jobs/.test(await projectRow.innerText()),
          await projectRow.innerText());
    check("and reports a non-zero size, not 0 B",
          !/\b0 B\b/.test(await projectRow.innerText()), await projectRow.innerText());
    check("the section total renders too",
          (await page.locator('[data-testid="projects-total"]').innerText()).includes("2 jobs"));

    console.log("\n== Show archived brings them back, badged ==");
    await page.check(SHOW_ARCHIVED);
    await page.waitForFunction(
      (id) => document.querySelector(`[data-testid="jobmanager-row-${id}"]`),
      a, { timeout: 15000 },
    );
    check("the archived jobs are listed again", (await row(page, a).count()) === 1);
    const badge = page.locator(`[data-testid="jobmanager-project-badge-${a}"]`);
    check("an archived row carries a project badge", await badge.isVisible());
    check("and the badge names the project", (await badge.innerText()).includes("qatest study one"));
    check("the unarchived job has no badge",
          (await page.locator(`[data-testid="jobmanager-project-badge-${c}"]`).count()) === 0);
    check("an archived row offers a one-click return",
          await page.locator(`[data-testid="jobmanager-unarchive-${a}"]`).isVisible());

    console.log("\n== searching by project name finds its jobs ==");
    await page.fill('[data-testid="jobmanager-search"]', "qatest study one");
    await page.waitForTimeout(300);
    check("typing the project's name pulls up its jobs",
          (await rowCount(page)) === 2, `${await rowCount(page)} rows`);
    await page.click('[data-testid="jobmanager-search-clear"]');
    await page.waitForTimeout(200);

    console.log("\n== the project opens to its jobs ==");
    await page.click(`[data-testid="project-open-${projectId}"]`);
    await page.waitForSelector('[data-testid="project-flyout-summary"]', { timeout: 15000 });
    check("the flyout renders with a summary line",
          (await page.locator('[data-testid="project-flyout-summary"]').innerText()).includes("2 jobs"));
    check("it lists exactly the two member jobs",
          (await page.locator('[data-testid^="project-job-row-"]').count()) === 2);
    check("the download control renders",
          await page.locator('[data-testid="project-flyout-download"]').isVisible());

    console.log("\n== returning one job to the job manager ==");
    await page.check(`[data-testid="project-job-check-${b}"]`);
    await page.click('[data-testid="project-flyout-return-selected"]');
    await page.waitForFunction(
      () => document.querySelectorAll('[data-testid^="project-job-row-"]').length === 1,
      undefined, { timeout: 15000 },
    );
    check("the flyout now lists one job", true);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);

    await page.uncheck(SHOW_ARCHIVED);
    await page.waitForFunction(
      (id) => document.querySelector(`[data-testid="jobmanager-row-${id}"]`),
      b, { timeout: 15000 },
    );
    check("the returned job is in the job manager without Show archived",
          (await row(page, b).count()) === 1);
    check("and the one still filed away is not", (await row(page, a).count()) === 0);
    check("the project row now reads one job",
          /1 job\b/.test(await page.locator(`[data-testid="project-row-${projectId}"]`).innerText()),
          await page.locator(`[data-testid="project-row-${projectId}"]`).innerText());

    console.log("\n== a job belongs to one project at a time ==");
    const second = await page.request.post(`${BASE_URL}/api/projects`, {
      headers: { Origin: BASE_URL }, data: { name: "qatest study two" },
    });
    const secondId = (await second.json()).project_id;
    projectIds.push(secondId);
    await page.check(SHOW_ARCHIVED);
    await page.waitForSelector(`[data-testid="jobmanager-row-${a}"]`, { timeout: 15000 });
    await row(page, a).locator('input[type="checkbox"]').check();
    await page.click(ADD_TO_PROJECT);
    await page.waitForSelector(POPOVER, { timeout: 10000 });
    check("the popover lists existing projects to file into",
          (await page.locator('[data-testid^="add-to-project-"]').count()) >= 2);
    await page.click(`[data-testid="add-to-project-${secondId}"]`);
    await page.waitForFunction(
      (id) => {
        const el = document.querySelector(`[data-testid="jobmanager-project-badge-${id}"]`);
        return el && el.innerText.includes("qatest study two");
      },
      a, { timeout: 15000 },
    );
    check("the job moved to the second project", true);
    check("and the first project is now empty rather than still claiming it",
          /0 jobs/.test(await page.locator(`[data-testid="project-row-${projectId}"]`).innerText()),
          await page.locator(`[data-testid="project-row-${projectId}"]`).innerText());

    console.log("\n== renaming a project ==");
    await page.locator(`[data-testid="project-row-${secondId}"]`).hover();
    await page.click(`[data-testid="project-rename-${secondId}"]`);
    await page.fill(`[data-testid="project-rename-input-${secondId}"]`, "qatest renamed study");
    await page.keyboard.press("Enter");
    await page.waitForFunction(
      (id) => {
        const el = document.querySelector(`[data-testid="project-row-${id}"]`);
        return el && el.innerText.includes("qatest renamed study");
      },
      secondId, { timeout: 15000 },
    );
    check("the new name renders in the rail", true);
    await page.waitForFunction(
      (id) => {
        const el = document.querySelector(`[data-testid="jobmanager-project-badge-${id}"]`);
        return el && el.innerText.includes("qatest renamed study");
      },
      a, { timeout: 15000 },
    );
    check("and reaches the archived job's badge", true);

    console.log("\n== searching the archive itself ==");
    await page.fill('[data-testid="projects-search"]', "renamed");
    await page.waitForTimeout(300);
    check("searching the rail narrows to the matching project",
          (await page.locator('[data-testid^="project-row-"]').count()) === 1);
    await page.fill('[data-testid="projects-search"]', "zzqqxx");
    await page.waitForTimeout(300);
    check("a nonsense query says so rather than showing nothing at all",
          await page.locator('[data-testid="projects-search-empty"]').isVisible());
    await page.fill('[data-testid="projects-search"]', "");
    await page.waitForTimeout(200);

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
