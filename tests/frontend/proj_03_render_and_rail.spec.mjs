/**
 * The pure rendering pass for the project archive: that every new piece of
 * UI is actually on screen, at both rail widths, in an empty account and a
 * full one, and after the rail has been collapsed and the page reloaded.
 *
 * This exists because the two traps here are both invisible to a
 * behavioural test.
 *
 * The first is the one LeftRail.tsx's own comment records: leftRailCollapsed
 * is persisted to localStorage, so a control that exists only in the
 * expanded branch is gone for good once somebody collapses the sidebar. A
 * spec that never collapses and never reloads will never see it. (Files had
 * exactly this gap until Projects was added, which is how it was noticed.)
 *
 * The second is that each rail section sits in its own PanelErrorBoundary.
 * A component that throws during render leaves a working-looking app with
 * one quiet fallback in the rail, every other test still passing, and the
 * API returning perfectly good data the whole time.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/proj_03_render_and_rail.spec.mjs
 */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, summary,
} from "./_helpers.mjs";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

// A name long enough to overflow a 220px rail several times over. The
// question is whether it truncates or widens the panel.
const LONG_NAME = "qatest an extremely long project name that should truncate rather than widen the rail";

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

/** Any PanelErrorBoundary that has tripped, anywhere on the page. */
async function boundaryFallbacks(page) {
  return page.evaluate(() =>
    /Something went wrong|failed to render|couldn't be displayed/i.test(document.body.innerText));
}

async function pageScrollsSideways(page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_projrender_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1400, height: 900 });
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
    const me = await (await page.request.get(`${BASE_URL}/api/auth/me`)).json();

    console.log("\n== an account with no projects at all ==");
    check("the section starts collapsed, like Knowledge base and Files",
          (await page.locator('[data-testid="section-projects-panel"]').count()) === 0);
    await openProjects(page);
    await page.waitForSelector('[data-testid="projects-empty"]', { timeout: 15000 });
    check("the empty state renders rather than a blank section", true);
    check("no error boundary has tripped", !(await boundaryFallbacks(page)));
    check("the search box is hidden while there is nothing to search",
          (await page.locator('[data-testid="projects-search"]').count()) === 0);
    check("and so is the totals line",
          (await page.locator('[data-testid="projects-total"]').count()) === 0);

    console.log("\n== the collapsed rail keeps a Projects icon ==");
    // The load-bearing part is the RELOAD: leftRailCollapsed comes back
    // from localStorage, so this is the state a returning user lands in.
    await page.click('[title="Collapse sidebar"]');
    await page.waitForTimeout(300);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[title="Expand sidebar"]', { timeout: 15000 });
    check("the rail is still collapsed after a reload", true);
    check("the collapsed rail shows a Projects icon",
          (await page.locator('[title="Projects"]').count()) > 0,
          "a section reachable only from the expanded rail is gone for good once somebody collapses it");
    check("and a Files icon, which was missing before this feature added one",
          (await page.locator('[title="Files"]').count()) > 0);
    await page.click('[title="Expand sidebar"]');
    await page.waitForSelector('[data-testid="section-projects-toggle"]', { timeout: 15000 });
    check("expanding brings the section back", true);

    console.log("\n== the section collapses and expands on its own ==");
    await openProjects(page);
    await page.click('[data-testid="section-projects-toggle"]');
    await page.waitForTimeout(250);
    check("collapsing hides the body",
          (await page.locator('[data-testid="section-projects-panel"]').count()) === 0);
    check("and says so to a screen reader",
          (await page.locator('[data-testid="section-projects-toggle"]').getAttribute("aria-expanded")) === "false");
    await page.click('[data-testid="section-projects-toggle"]');
    await page.waitForSelector('[data-testid="section-projects-panel"]', { timeout: 10000 });
    check("expanding brings it back", true);

    console.log("\n== a project with a very long name, and a job ==");
    const jobId = seedJob(me.id, "qatest render probe");
    jobIds.push(jobId);
    const r = await page.request.post(`${BASE_URL}/api/projects`, {
      headers: { Origin: BASE_URL }, data: { name: LONG_NAME, job_ids: [jobId] },
    });
    const projectId = (await r.json()).project_id;
    projectIds.push(projectId);
    await openProjects(page);
    await page.waitForSelector(`[data-testid="project-row-${projectId}"]`, { timeout: 20000 });
    check("the project row renders", true);
    check("the totals line appears once there is something to total",
          await page.locator('[data-testid="projects-total"]').isVisible());
    check("no error boundary tripped with real content in the section",
          !(await boundaryFallbacks(page)));

    console.log("\n== at the narrowest rail width ==");
    const railWidth = async () =>
      page.evaluate(() => {
        const el = document.querySelector('[data-testid="section-projects-toggle"]');
        return el ? el.closest("div.flex.min-w-0.shrink-0.flex-col").getBoundingClientRect().width : null;
      });
    const setRail = async (width) => {
      await page.evaluate((w) => {
        const raw = localStorage.getItem("qc-agent-layout");
        const parsed = raw ? JSON.parse(raw) : { state: {}, version: 0 };
        parsed.state = { ...parsed.state, leftRailWidth: w, leftRailCollapsed: false };
        localStorage.setItem("qc-agent-layout", JSON.stringify(parsed));
      }, width);
      await page.reload({ waitUntil: "domcontentloaded" });
      await openProjects(page);
      await page.waitForSelector(`[data-testid="project-row-${projectId}"]`, { timeout: 20000 });
    };

    await setRail(220);
    check("the rail really is at its minimum width",
          Math.round(await railWidth()) === 220, String(await railWidth()));
    check("the project row still renders at 220px",
          await page.locator(`[data-testid="project-row-${projectId}"]`).isVisible());
    check("the long name does not push the row wider than the rail",
          await page.evaluate((id) => {
            const row = document.querySelector(`[data-testid="project-row-${id}"]`);
            const rail = row.closest("div.flex.min-w-0.shrink-0.flex-col");
            return row.getBoundingClientRect().right <= rail.getBoundingClientRect().right + 1;
          }, projectId),
          "a long project name is widening the rail instead of truncating");
    check("and the page itself does not scroll sideways", !(await pageScrollsSideways(page)));
    check("the job count and size are still legible beside it",
          /1 job/.test(await page.locator(`[data-testid="project-row-${projectId}"]`).innerText()),
          await page.locator(`[data-testid="project-row-${projectId}"]`).innerText());

    console.log("\n== and at the widest ==");
    await setRail(520);
    check("the rail really is at its maximum width",
          Math.round(await railWidth()) === 520, String(await railWidth()));
    check("the project row still renders at 520px",
          await page.locator(`[data-testid="project-row-${projectId}"]`).isVisible());
    check("the page still does not scroll sideways", !(await pageScrollsSideways(page)));
    check("no error boundary tripped at either width", !(await boundaryFallbacks(page)));

    console.log("\n== the row's controls are reachable ==");
    await page.locator(`[data-testid="project-row-${projectId}"]`).hover();
    for (const [name, sel] of [
      ["rename", `[data-testid="project-rename-${projectId}"]`],
      ["download", `[data-testid="project-download-${projectId}"]`],
      ["delete", `[data-testid="project-delete-${projectId}"]`],
    ]) {
      check(`the ${name} control renders on hover`, await page.locator(sel).isVisible());
    }

    console.log("\n== the flyout renders its own contents ==");
    await page.click(`[data-testid="project-open-${projectId}"]`);
    await page.waitForSelector('[data-testid="project-flyout-summary"]', { timeout: 15000 });
    check("the flyout opens with a summary", true);
    check("its title is the project's name",
          (await page.locator('[role="dialog"]').first().innerText()).includes("qatest an extremely long"));
    check("the job table renders inside it",
          (await page.locator('[data-testid^="project-job-row-"]').count()) === 1);
    check("with a select-all and a return control",
          (await page.locator('[data-testid="project-flyout-select-all"]').isVisible())
          && (await page.locator('[data-testid="project-flyout-return-selected"]').isVisible()));
    check("the flyout does not make the page scroll sideways", !(await pageScrollsSideways(page)));
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);

    console.log("\n== an empty project reads as empty, not as broken ==");
    const r2 = await page.request.post(`${BASE_URL}/api/projects`, {
      headers: { Origin: BASE_URL }, data: { name: "qatest empty one" },
    });
    const emptyId = (await r2.json()).project_id;
    projectIds.push(emptyId);
    await openProjects(page);
    await page.waitForSelector(`[data-testid="project-row-${emptyId}"]`, { timeout: 20000 });
    check("an empty project shows 0 jobs rather than nothing",
          /0 jobs/.test(await page.locator(`[data-testid="project-row-${emptyId}"]`).innerText()),
          await page.locator(`[data-testid="project-row-${emptyId}"]`).innerText());
    await page.locator(`[data-testid="project-row-${emptyId}"]`).hover();
    check("its download control is disabled, since there is nothing to package",
          await page.locator(`[data-testid="project-download-${emptyId}"]`).isDisabled());
    await page.click(`[data-testid="project-open-${emptyId}"]`);
    await page.waitForSelector('[data-testid="project-flyout-empty"]', { timeout: 15000 });
    check("and its flyout explains how to fill it",
          (await page.locator('[data-testid="project-flyout-empty"]').innerText()).includes("Add to project"));
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);

    console.log("\n== the job manager's own empty state stays honest ==");
    // With the only job archived and Show archived off, this list is empty
    // for a reason the user needs told, or archiving looks like deletion.
    await page.waitForFunction(
      () => document.querySelector('[data-testid="jobmanager-empty"]')
         || document.querySelectorAll('[data-testid^="jobmanager-row-"]').length > 0,
      undefined, { timeout: 20000 },
    );
    if (await page.locator('[data-testid="jobmanager-empty"]').count()) {
      check("an empty job list says the jobs are archived rather than gone",
            (await page.locator('[data-testid="jobmanager-empty"]').innerText()).includes("archive"));
      check("and the Show archived toggle survives the empty state",
            await page.locator('[data-testid="jobmanager-show-archived-empty"]').isVisible(),
            "otherwise somebody who archived everything has no route back from this panel");
    } else {
      // Not a PASS. This branch could not be exercised on this deployment,
      // and saying "checked" about something that never ran is worse than
      // saying nothing. A job with no recorded owner is deliberately
      // visible to every user (see app/auth/ownership.py), so any dev
      // stack carrying unowned jobs shows them to a brand-new account and
      // the job manager is never empty for one. Reachable on a clean
      // deployment, or by archiving every visible job first.
      console.log("[NOTE] the job manager's empty state was not reachable here: unowned jobs "
                  + "are visible to every user, so a fresh account never sees an empty list");
    }

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
