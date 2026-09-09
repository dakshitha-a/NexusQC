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
const SEARCH_OPEN = '[data-testid="jobmanager-search-open"]';
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
    await page.waitForSelector(SEARCH_OPEN, { timeout: 30000 });
    await page.waitForFunction(
      (ids) => ids.every((id) => document.querySelector(`[data-testid="jobmanager-row-${id}"]`)),
      [a, b], { timeout: 30000 },
    );

    console.log("\n== the controls cost the list no rows at all ==");
    // This block used to check that the search box and the "Show archived"
    // checkbox shared one line instead of stacking into two. They now share no
    // line: both are icons in the section header, and the search INPUT opens as
    // a row in the body only while it is in use. That is the same complaint
    // taken further -- this is the app's only flex-1 pane, so a row spent above
    // the list is a row of jobs not shown, and it was being spent whether or
    // not anybody was filtering.
    check("the search box is not there until it is asked for",
          (await page.locator(SEARCH).count()) === 0);
    check("but its control is, in the section header",
          await page.locator(SEARCH_OPEN).isVisible());
    check("and so is the archive control",
          await page.locator(TOGGLE).isVisible());

    const inHeader = await page.evaluate(([o, t]) => {
      const header = document.querySelector('[data-testid="section-job-manager-all-jobs-toggle"]')
        .parentElement.getBoundingClientRect();
      const within = (sel) => {
        const r = document.querySelector(sel).getBoundingClientRect();
        return r.top >= header.top - 2 && r.bottom <= header.bottom + 2;
      };
      return { search: within(o), toggle: within(t) };
    }, [SEARCH_OPEN, TOGGLE]);
    check("both sit on the section header's own line", inHeader.search && inHeader.toggle,
          JSON.stringify(inHeader));

    const listTopBefore = (await page.locator(`[data-testid="jobmanager-row-${a}"]`).boundingBox()).y;
    await page.click(SEARCH_OPEN);
    await page.waitForSelector(SEARCH, { timeout: 5000 });
    const listTopAfter = (await page.locator(`[data-testid="jobmanager-row-${a}"]`).boundingBox()).y;
    check("opening the search pushes the list down, and only then",
          listTopAfter > listTopBefore,
          `first row was at y=${Math.round(listTopBefore)}, now ${Math.round(listTopAfter)}`);

    console.log("\n== the archive control still says what it is ==");
    check("it is a pressed-state button, readable to a screen reader",
          (await page.locator(TOGGLE).getAttribute("aria-pressed")) === "false"
          && (await page.locator(TOGGLE).getAttribute("aria-label")) === "Show archived jobs");
    await page.click(TOGGLE);
    await page.waitForTimeout(300);
    check("and pressing it flips that state",
          (await page.locator(TOGGLE).getAttribute("aria-pressed")) === "true");
    await page.click(TOGGLE);
    await page.waitForTimeout(300);

    console.log("\n== the search box still works ==");
    // Reopened: an empty search box closes itself when focus leaves it, which
    // the archive clicks above did. A box holding a query never closes on
    // blur, since a panel silently filtered by a query nobody can see is a
    // list that appears to have lost rows.
    if ((await page.locator(SEARCH).count()) === 0) {
      await page.click(SEARCH_OPEN);
      await page.waitForSelector(SEARCH, { timeout: 5000 });
    }
    await page.fill(SEARCH, "alpha");
    await page.waitForTimeout(250);
    check("searching still filters", (await row(page, a).count()) === 1 && (await row(page, b).count()) === 0);
    const countText = await page.$eval(SEARCH, (el) => el.closest("div").parentElement.innerText);
    check("and the match count still appears", /1 of \d+/.test(countText),
          `row text was ${JSON.stringify(countText.replace(/\n/g, " | "))}`);
    await page.click('[data-testid="jobmanager-search-clear"]');
    await page.waitForTimeout(200);
    check("clearing empties the box without taking it away",
          (await page.inputValue(SEARCH)) === "");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
    check("and Escape closes it, giving the row back",
          (await page.locator(SEARCH).count()) === 0);

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
