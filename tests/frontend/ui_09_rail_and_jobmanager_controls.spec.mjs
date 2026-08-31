/**
 * Three controls that were either missing or wasting a row.
 *
 *  * The Job Manager's search box and its "Show archived" toggle shared a
 *    panel but not a line. That panel is the app's only flex-1 pane, so a
 *    row spent above the list is a row of jobs not shown.
 *  * A selection of jobs could be attached to a prompt or filed into a
 *    project, but not simply cleared: the only way out was to untick every
 *    row by hand.
 *  * The collapsed left rail's icons were decorative divs. A collapsed rail
 *    told you which sections existed and reached none of them.
 *
 * The rail icons are the part that needs a browser most. They only exist in
 * the collapsed branch, and leftRailCollapsed is persisted, so the state
 * being tested here is the one a returning user lands in and not one a
 * fresh page load ever shows.
 *
 * Raw Playwright, chromium, headless -- no @playwright/test runner, same
 * convention as the rest of tests/frontend.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/ui_09_rail_and_jobmanager_controls.spec.mjs
 */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, summary,
} from "./_helpers.mjs";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SEARCH = '[data-testid="jobmanager-search"]';
const TOGGLE = '[data-testid="jobmanager-show-archived"]';
const CLEAR = '[data-testid="jobmanager-clear-selection"]';

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

const row = (page, id) => page.locator(`[data-testid="jobmanager-row-${id}"]`);

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_controls_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1500, height: 900 });
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 200)));
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
  });

  const jobIds = [];
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

    console.log("\n== seed two jobs so the search box and selection bar exist ==");
    const a = seedJob(me.id, "qatest control alpha");
    const b = seedJob(me.id, "qatest control bravo");
    jobIds.push(a, b);
    await page.waitForSelector(SEARCH, { timeout: 30000 });
    await page.waitForFunction(
      (ids) => ids.every((id) => document.querySelector(`[data-testid="jobmanager-row-${id}"]`)),
      [a, b], { timeout: 30000 },
    );

    console.log("\n== search and Show archived share one line ==");
    const geom = await page.evaluate(([s, t]) => {
      const box = document.querySelector(s).getBoundingClientRect();
      const tog = document.querySelector(t).closest("label").getBoundingClientRect();
      const panel = document.querySelector(s).closest("div.border-b").getBoundingClientRect();
      return {
        searchTop: box.top, searchBottom: box.bottom, searchRight: box.right, searchWidth: box.width,
        toggleTop: tog.top, toggleBottom: tog.bottom, toggleLeft: tog.left,
        panelRight: panel.right, panelWidth: panel.width,
      };
    }, [SEARCH, TOGGLE]);
    const overlapY = Math.min(geom.searchBottom, geom.toggleBottom) - Math.max(geom.searchTop, geom.toggleTop);
    check("both controls are visible", await page.locator(SEARCH).isVisible()
          && await page.locator(TOGGLE).isVisible());
    check("they occupy the same line, not stacked rows",
          overlapY > 0,
          `search y ${Math.round(geom.searchTop)}-${Math.round(geom.searchBottom)}, `
          + `toggle y ${Math.round(geom.toggleTop)}-${Math.round(geom.toggleBottom)}`);
    check("the toggle sits to the right of the search box rather than over it",
          geom.toggleLeft >= geom.searchRight - 2,
          `search ends at ${Math.round(geom.searchRight)}, toggle starts at ${Math.round(geom.toggleLeft)}`);
    check("the search box gave up the width and still has a usable amount",
          geom.searchWidth < geom.panelWidth * 0.8 && geom.searchWidth > 90,
          `search is ${Math.round(geom.searchWidth)}px in a ${Math.round(geom.panelWidth)}px panel`);
    check("the toggle's label is not wrapped or clipped away",
          (await page.locator(TOGGLE).locator("xpath=..").innerText()).includes("Show archived"));
    check("and neither control spills out of the panel",
          geom.toggleLeft < geom.panelRight && geom.searchRight <= geom.panelRight + 2);

    console.log("\n== the search box still works at its new width ==");
    await page.fill(SEARCH, "alpha");
    await page.waitForTimeout(250);
    check("searching still filters", (await row(page, a).count()) === 1 && (await row(page, b).count()) === 0);
    // Read the panel's own text rather than a Playwright text= regex, which
    // has to survive two layers of escaping to get here and silently matches
    // nothing when it does not.
    const countText = await page.$eval(SEARCH, (el) => el.closest("div.border-b").innerText);
    check("and the match count still appears", /1 of \d+ jobs?/.test(countText),
          `header text was ${JSON.stringify(countText.replace(/\n/g, " | "))}`);
    await page.click('[data-testid="jobmanager-search-clear"]');
    await page.waitForTimeout(200);

    console.log("\n== a selection can be cleared ==");
    check("there is no clear button with nothing selected", (await page.locator(CLEAR).count()) === 0);
    await row(page, a).locator('input[type="checkbox"]').check();
    await row(page, b).locator('input[type="checkbox"]').check();
    await page.waitForSelector(CLEAR, { timeout: 10000 });
    check("the clear button appears with the selection bar", true);
    check("it is icon-only, carrying no text",
          (await page.locator(CLEAR).innerText()).trim() === "",
          `button text was ${JSON.stringify((await page.locator(CLEAR).innerText()).trim())}`);
    check("but it is still named for a screen reader and a tooltip",
          (await page.locator(CLEAR).getAttribute("aria-label")) === "Clear selection"
          && (await page.locator(CLEAR).getAttribute("title")) === "Clear selection");
    check("it sits alongside the other two actions, not replacing them",
          (await page.locator('[data-testid="jobmanager-add-to-project"]').isVisible())
          && (await page.locator('[data-testid="jobmanager-attach-to-prompt"]').isVisible()));

    await page.click(CLEAR);
    await page.waitForTimeout(300);
    check("clicking it empties the selection bar", (await page.locator(CLEAR).count()) === 0);
    check("and unticks every row",
          (await page.locator('[data-testid^="jobmanager-row-"] input[type="checkbox"]:checked').count()) === 0);
    check("without attaching anything to the prompt",
          (await page.locator('[data-testid^="jobmanager-detach-job-"]').count()) === 0,
          "clearing must not be a disguised attach");

    console.log("\n== the collapsed rail's icons reach their sections ==");
    await page.click('[title="Collapse sidebar"]');
    await page.waitForTimeout(300);
    // The reload is the point: leftRailCollapsed is persisted, so this is
    // the state a returning user actually lands in.
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[title="Expand sidebar"]', { timeout: 15000 });

    for (const [section, panel] of [
      ["projects", "section-projects-panel"],
      ["files", "section-files-panel"],
      ["kb", "section-knowledge-base-panel"],
    ]) {
      const sel = `[data-testid="rail-collapsed-${section}"]`;
      check(`the collapsed rail has a ${section} control`, (await page.locator(sel).count()) === 1);
      check(`and it is a button rather than a decorative div`,
            (await page.locator(sel).evaluate((el) => el.tagName)) === "BUTTON",
            "a div with a tooltip shows that a section exists and reaches none of it");
      await page.click(sel);
      await page.waitForSelector(`[data-testid="${panel}"]`, { timeout: 10000 });
      check(`clicking it expands the rail and opens ${section}`,
            (await page.locator('[title="Collapse sidebar"]').count()) === 1
            && (await page.locator(`[data-testid="${panel}"]`).isVisible()));
      // Back to collapsed for the next one.
      await page.click('[title="Collapse sidebar"]');
      await page.waitForTimeout(250);
    }

    const convSel = '[data-testid="rail-collapsed-conversations"]';
    check("the conversations control is there too", (await page.locator(convSel).count()) === 1);
    await page.click(convSel);
    await page.waitForSelector('[data-testid="conversation-list"]', { timeout: 10000 });
    check("and it expands the rail onto the conversation list",
          await page.locator('[data-testid="conversation-list"]').isVisible());

    console.log("\n== the opened section survives a reload ==");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="section-knowledge-base-panel"]', { timeout: 15000 });
    check("a section opened from the rail is still open after a reload",
          await page.locator('[data-testid="section-knowledge-base-panel"]').isVisible(),
          "the collapse state moved into the persisted layout store, like the right dock's sections");

    check("no console or page errors during the whole run",
          consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
  } catch (err) {
    check("the run completed without throwing", false, String(err).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 900));
    } catch {}
  } finally {
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
