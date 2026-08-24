// The Job Manager row is one click target, everywhere except its controls.
//
// Reported as "sometimes it takes a couple of clicks to open a job preview
// from the job manager", asked as a latency question. It was not latency:
// the job's name was a dead click zone. Renaming lived on a double-click on
// that name, and since a browser fires click, click, dblclick in sequence,
// the single click had to be swallowed to stop the drawer opening mid-
// rename. The name is a block element spanning the whole name column, so
// the widest and most obvious target in the row -- measured here at 251 of
// the row's 419 px -- was the one place a click did nothing. A second click
// landing a few pixels lower, on the job-id line, worked, which is what
// made it read as lag.
//
// What this pins down:
//
// 1. Every part of the row that is not a control opens the preview: the
//    name line (the regression), the job-id line under it, the status dot
//    and the relative-time cell.
// 2. The controls still act on the row instead of opening it -- the select
//    checkbox, the rename button and the delete button.
// 3. Rename still works, now from an explicit button rather than a
//    double-click, and the drawer stays shut while it is being typed into.
// 4. The action column grew to hold the rename button next to delete's
//    two-button confirm state, so re-check what ui_06 established: the
//    list must not scroll sideways and delete must stay inside the panel.
//
// Run against the real docker-compose dev stack (needs a rebuilt
// frontend/dist -- nginx serves it from a host bind mount):
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/ui_07_row_click_target.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const LABEL = "row click target probe, water single point";
const RENAMED = "renamed by ui_07";

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 320000,
  }).trim();
}

const drawerOpen = (page) => page.$('[role="dialog"]').then((h) => !!h);

async function closeDrawer(page) {
  if (await drawerOpen(page)) {
    await page.keyboard.press("Escape");
    await page.waitForSelector('[role="dialog"]', { state: "detached", timeout: 5000 });
  }
}

/** Click the middle of a box the page measured for us, rather than a
 *  selector: the point of this spec is WHERE in the row the click lands,
 *  and Playwright's own element click would just centre on whatever
 *  element the selector picked. Capped at 60px in from the left edge so
 *  the click stays over the text rather than out in the fade. */
async function clickBox(page, box) {
  await page.mouse.click(box.x + Math.min(box.w / 2, 60), box.y + box.h / 2);
  await page.waitForTimeout(600);
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_ui07_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  let jobId = null;

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
    // The unauthenticated first paint probes /api/auth/me and gets a 401,
    // which the browser logs as a console error before there is any session
    // to have. Only what happens once logged in is this spec's business.
    consoleErrors.length = 0;

    const users = await (await adminCtx.request.get(`${BASE_URL}/api/admin/users`)).json();
    const user = users.find((u) => u.username === username);
    check("found the just-registered user via the admin API", !!user, username);

    console.log("\n== seed one completed single point ==");
    const seeded = JSON.parse(execApi(`
import json, time
from app.chemistry.jobs.base import JobSpec, get_job_manager, write_meta
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
mgr = get_job_manager()
jid = mgr.submit(
    JobSpec(task="single_point", method="hf", engine="pyscf", molecule=WATER,
            params={"basis": "sto-3g"}),
    owner_user_id="${user.id}",
)
# The display label is the mutable one in meta.json, which is what a rename
# writes and what both job lists render -- JobSpec.label is only a seed.
write_meta(jid, {"label": ${JSON.stringify(LABEL)}})
status = None
deadline = time.time() + 180
while time.time() < deadline:
    status = (mgr.status(jid) or {}).get("status")
    if status in ("completed", "failed", "cancelled"):
        break
    time.sleep(0.5)
print(json.dumps({"job_id": jid, "status": status}))
`).split("\n").pop());
    jobId = seeded.job_id;
    check("the seeded single point reached status=completed", seeded.status === "completed", seeded.status);

    const rowSel = `[data-testid="jobmanager-row-${jobId}"]`;
    await page.waitForSelector(rowSel, { timeout: 20000 });

    // Measure the row's parts once. divs[0] is the name line, divs[1] the
    // "<job id> · <engine>" line under it.
    const geom = await page.$eval(rowSel, (tr) => {
      const box = (el) => {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, w: r.width, h: r.height };
      };
      const nameCell = tr.querySelector("td:nth-child(3)");
      const lines = [...nameCell.querySelectorAll(":scope > div")].map(box);
      return {
        row: box(tr),
        name: lines[0],
        idLine: lines[1],
        statusCell: box(tr.querySelector("td:nth-child(2)")),
        timeCell: box(tr.querySelector("td:nth-child(4)")),
        checkbox: box(tr.querySelector('input[type="checkbox"]')),
      };
    });
    console.log(`name line is ${Math.round(geom.name.w)}x${Math.round(geom.name.h)} px ` +
      `of a ${Math.round(geom.row.w)}x${Math.round(geom.row.h)} px row`);

    console.log("\n== every non-control part of the row opens the preview ==");
    for (const [what, box] of [
      ["name line", geom.name],
      ["job-id line", geom.idLine],
      ["status dot cell", geom.statusCell],
      ["relative-time cell", geom.timeCell],
    ]) {
      await clickBox(page, box);
      const opened = await drawerOpen(page);
      check(`clicking the ${what} opens the preview drawer`, opened,
        opened ? "" : "no dialog after 600ms -- dead click zone");
      await closeDrawer(page);
    }

    console.log("\n== the row's own controls do not open it ==");
    await clickBox(page, geom.checkbox);
    check("clicking the select checkbox does not open the preview", !(await drawerOpen(page)));
    const selectedBanner = await page.textContent("body");
    check("clicking the select checkbox does select the row",
      selectedBanner.includes("1 selected"));
    await clickBox(page, geom.checkbox);
    await closeDrawer(page);

    const delRect = await page.$eval(`[data-testid="job-delete-${jobId}"]`, (el) => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    });
    await clickBox(page, delRect);
    check("clicking delete does not open the preview underneath the confirm",
      !(await drawerOpen(page)));
    check("clicking delete shows its confirm pair",
      !!(await page.$(`[data-testid="job-delete-confirm-${jobId}"]`)));
    await page.click(`[data-testid="job-delete-dismiss-${jobId}"]`);
    await closeDrawer(page);

    console.log("\n== rename, from a button rather than a double-click ==");
    await page.click(`[data-testid="jobmanager-rename-${jobId}"]`);
    await page.waitForTimeout(400);
    check("the rename button does not open the preview", !(await drawerOpen(page)));
    const input = await page.$(`${rowSel} input[type="text"], ${rowSel} td:nth-child(3) input:not([type="checkbox"])`);
    check("the rename button puts the row into an editable field", !!input);
    if (input) {
      await input.fill(RENAMED);
      await page.keyboard.press("Enter");
      await page.waitForFunction(
        ([sel, want]) => document.querySelector(sel)?.textContent?.includes(want),
        [rowSel, RENAMED], { timeout: 10000 },
      );
      check("the rename persisted to the row", true, RENAMED);
    }
    await closeDrawer(page);

    console.log("\n== the wider action column still fits the panel ==");
    const mgrBox = await page.evaluate((sel) => {
      const scroller = document.querySelector(sel).closest(".overflow-y-auto");
      const r = scroller.getBoundingClientRect();
      return {
        scrollWidth: scroller.scrollWidth, clientWidth: scroller.clientWidth,
        rect: { left: r.left, right: r.right },
      };
    }, `[data-testid="job-delete-${jobId}"]`);
    check("the Job Manager list does not scroll sideways",
      mgrBox.scrollWidth <= mgrBox.clientWidth + 1,
      `scrollWidth=${mgrBox.scrollWidth} clientWidth=${mgrBox.clientWidth}`);
    for (const [what, sel] of [
      ["delete", `[data-testid="job-delete-${jobId}"]`],
      ["rename", `[data-testid="jobmanager-rename-${jobId}"]`],
    ]) {
      const r = await page.$eval(sel, (el) => {
        const b = el.getBoundingClientRect();
        return { left: b.left, right: b.right, w: b.width, h: b.height };
      });
      check(`the ${what} button is inside the panel and not clipped away`,
        r.left >= mgrBox.rect.left && r.right <= mgrBox.rect.right && r.w >= 16 && r.h >= 16,
        `${Math.round(r.left)}-${Math.round(r.right)} vs panel ${Math.round(mgrBox.rect.left)}-${Math.round(mgrBox.rect.right)}, ${Math.round(r.w)}x${Math.round(r.h)}`);
    }

    check("no console errors during any of this", consoleErrors.length === 0,
      consoleErrors.slice(0, 3).join(" | "));
  } finally {
    // Tests clean up the jobs they create -- a suite run must leave no
    // clutter in anyone's job list (see tests/README.md).
    if (jobId) {
      try {
        execApi(`
from app.chemistry.jobs.base import delete_job_dir
delete_job_dir("${jobId}")
print("deleted")
`);
      } catch (e) {
        console.log("cleanup failed:", String(e).slice(0, 200));
      }
    }
    await browser.close();
  }
  process.exit(summary() ? 0 : 1);
}

main();
