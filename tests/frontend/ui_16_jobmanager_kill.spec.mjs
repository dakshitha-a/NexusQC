// The Job Manager can now stop a job that is still going, and its rows spend
// their width on the job's name rather than on a timestamp column.
//
// ## What was wrong
//
// DeleteJobButton was rendered in the Job Manager disabled for pending and
// running jobs, with the tooltip "Cancel the job before deleting it", while
// KillButton was not rendered in that panel at all -- it lived only in the
// per-conversation Jobs panel and the job detail drawer. So a running job in
// the Job Manager showed one greyed-out control naming an action reachable
// nowhere on that surface. The two controls now swap: Stop while there is
// something to stop, Delete once there isn't.
//
// ## What this proves, and with which job
//
// Two seeded jobs, because no single one can show both halves honestly:
//
//   - A job forced to "running" proves the control swap, the two-step confirm
//     pair, the live hairline, and that none of it is clipped by the
//     fixed-width action column. It is NOT cancelled for real: it is a
//     finished job with a hand-written status and no worker behind it, so
//     JobManager.cancel() would correctly return False. The confirm is
//     dismissed instead.
//   - A job forced to "pending" proves the cancel path end to end. cancel()
//     handles a never-started job by writing the cancelled status directly
//     (app/chemistry/jobs/base.py, the `if proc is None` branch), so this one
//     really does travel button -> API -> status.json -> back to a row that
//     now offers Delete.
//
// Forcing the status is safe for the length of a run: the reconciler that
// would put these back runs only in JobManager.__init__, i.e. at server
// start, and nothing restarts the api container here.
//
// Geometry is asserted at the default text size and again at the largest
// (fontScale 1.35), because the action column is table-fixed and cannot grow:
// a clipped confirm pair would be a running job nobody can cancel, and it
// would look like nothing at all in a code read.
//
// Self-contained on the ui_06 pattern: its own user, its own thread, its own
// jobs, and it deletes the user (and with them the jobs) at the end.
//
// Run against the docker-compose dev stack, with frontend/dist REBUILT
// (nginx serves dist from a host bind mount):
//
//   npm --prefix frontend run build
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/ui_16_jobmanager_kill.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_ui16_" + Math.random().toString(36).slice(2, 8);
const APPEARANCE_KEY = "qc-agent-appearance";
const appearance = (over = {}) =>
  JSON.stringify({
    state: { theme: "balmer", accent: "hbeta", fontScale: 1, density: "cosy", motion: "full", ...over },
    version: 0,
  });

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 300000,
  }).trim();
}

/** Every control in a row's action cell, measured against the panel it scrolls
 *  inside. Returns null when the row isn't there. */
function measureRow(page, jobId) {
  return page.evaluate((id) => {
    const row = document.querySelector(`[data-testid="jobmanager-row-${id}"]`);
    if (!row) return null;
    const scroller = row.closest(".overflow-y-auto");
    const box = (el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, w: r.width, h: r.height };
    };
    const cells = [...row.querySelectorAll("td")];
    const controls = [...row.querySelectorAll("td:last-child button")].map((b) => ({
      testid: b.getAttribute("data-testid"),
      rect: box(b),
    }));
    const nameCell = row.querySelector('td[data-testid^="jobmanager-name-"]');
    return {
      cellCount: cells.length,
      nameWidth: nameCell ? nameCell.getBoundingClientRect().width : 0,
      rowWidth: box(row).w,
      controls,
      panel: box(scroller),
      scrollWidth: scroller.scrollWidth,
      clientWidth: scroller.clientWidth,
      hasLiveHairline: !!row.querySelector("td.hairline-live"),
      timeText: (row.querySelector('[data-testid^="job-time-"]') || {}).textContent || "",
      // The timestamp shares the id line now, so it must sit on the same
      // baseline row as the id rather than on a line of its own.
      timeOnIdLine: (() => {
        const t = row.querySelector('[data-testid^="job-time-"]');
        const idSpan = t && t.parentElement.querySelector("span");
        if (!t || !idSpan) return false;
        return Math.abs(t.getBoundingClientRect().top - idSpan.getBoundingClientRect().top) < 6;
      })(),
    };
  }, jobId);
}

/** True when `inner` sits inside `outer` with a small tolerance. */
function contains(outer, inner, slack = 2) {
  return (
    inner.left >= outer.left - slack && inner.right <= outer.right + slack &&
    inner.top >= outer.top - slack && inner.bottom <= outer.bottom + slack
  );
}

function describe(outer, inner) {
  const r = (n) => Math.round(n);
  return `x: ${r(inner.left)}-${r(inner.right)} in ${r(outer.left)}-${r(outer.right)}; ` +
    `y: ${r(inner.top)}-${r(inner.bottom)} in ${r(outer.top)}-${r(outer.bottom)}`;
}

/** Every control in the action cell is inside the panel and not squashed. */
function checkActionCell(m, label) {
  check(`${label}: the list does not scroll sideways`,
    m.scrollWidth <= m.clientWidth + 1, `scrollWidth=${m.scrollWidth} clientWidth=${m.clientWidth}`);
  for (const c of m.controls) {
    check(`${label}: ${c.testid} is inside the panel`,
      contains(m.panel, c.rect), describe(m.panel, c.rect));
    check(`${label}: ${c.testid} is not clipped to nothing`,
      c.rect.w >= 16 && c.rect.h >= 16, `${Math.round(c.rect.w)}x${Math.round(c.rect.h)}`);
  }
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_ui16_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  // The appearance is set by writing localStorage and reloading, never with
  // addInitScript: that runs on EVERY navigation, so it would stamp whatever
  // it was given back over a size the test had just changed, and the
  // large-text geometry checks would quietly measure the default size and
  // pass. A fresh profile starts at the store's own defaults anyway.
  const setAppearance = async (over) => {
    await page.evaluate(([k, v]) => window.localStorage.setItem(k, v), [APPEARANCE_KEY, appearance(over)]);
    await page.reload({ waitUntil: "domcontentloaded" });
  };
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  let seeded = null;
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

    // Everything before this point is the sign-up flow, whose unauthenticated
    // /api/me probe answers 401 by design. Only errors after login are this
    // spec's business.
    consoleErrors.length = 0;

    const usersRes = await adminCtx.request.get(`${BASE_URL}/api/admin/users`);
    const user = (await usersRes.json()).find((u) => u.username === username);
    check("found the just-registered user via the admin API", !!user, username);

    console.log("\n== seed three jobs: one done, one held running, one held pending ==");
    const seedCode = `
import json, time
from app.agent import threads as thread_registry
from app.auth.models import record_ownership
from app.chemistry.jobs.base import JobSpec, get_job_manager, write_meta, write_status

USER_ID = "${user.id}"
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}

thread = thread_registry.create_thread(label="${THREAD_LABEL}")
thread_id = thread["thread_id"]
record_ownership("thread", thread_id, USER_ID)

mgr = get_job_manager()
ids = []
for _ in range(3):
    ids.append(mgr.submit(
        JobSpec(task="single_point", method="hf", engine="pyscf", molecule=WATER,
                params={"basis": "sto-3g"}),
        owner_user_id=USER_ID,
    ))
done_id, running_id, pending_id = ids

# A name long enough that no plausible panel width fits it, so the width the
# timestamp column used to hold is measurably back in the name cell.
write_meta(done_id, {"label": "a single point on water with a deliberately unreasonable name 0123456789abcdef"})

deadline = time.time() + 280
while time.time() < deadline:
    st = {i: (mgr.status(i) or {}).get("status") for i in ids}
    if all(s in ("completed", "failed", "cancelled") for s in st.values()):
        break
    time.sleep(1.0)

# Held non-terminal by hand. The reconciler that would undo this runs only in
# JobManager.__init__, so it holds until the api container restarts.
write_status(running_id, "running", "held running by ui_16")
write_status(pending_id, "pending", "held pending by ui_16")

print(json.dumps({"thread_id": thread_id, "done_id": done_id,
                  "running_id": running_id, "pending_id": pending_id,
                  "settled": st}))
`;
    seeded = JSON.parse(execApi(seedCode).trim().split("\n").pop());
    console.log(`seeded: ${JSON.stringify(seeded)}`);
    check("all three seeded jobs reached a terminal status before being held",
      Object.values(seeded.settled).every((s) => s === "completed"),
      JSON.stringify(seeded.settled));

    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`[data-testid="jobmanager-row-${seeded.done_id}"]`, { timeout: 30000 });

    console.log("\n== a finished job offers Delete and no Stop ==");
    check("the finished row shows Delete",
      !!(await page.$(`[data-testid="job-delete-${seeded.done_id}"]`)));
    check("the finished row shows no Stop",
      !(await page.$(`[data-testid="jobmanager-kill-${seeded.done_id}"]`)));

    console.log("\n== a running job offers Stop and no Delete ==");
    await page.waitForSelector(`[data-testid="jobmanager-kill-${seeded.running_id}"]`, { timeout: 15000 });
    check("the running row shows Stop", true);
    check("the running row shows no Delete, which was the disabled control",
      !(await page.$(`[data-testid="job-delete-${seeded.running_id}"]`)));

    console.log("\n== the row spends its width on the name ==");
    const restRunning = await measureRow(page, seeded.running_id);
    const restDone = await measureRow(page, seeded.done_id);
    check("the row is four cells, the timestamp column having gone",
      restDone.cellCount === 4, `cellCount=${restDone.cellCount}`);
    check("the timestamp sits on the job-id line, not a line of its own",
      restDone.timeOnIdLine, `time="${restDone.timeText.trim()}"`);
    check("the timestamp still says something",
      /(now|ago)/.test(restDone.timeText), `time="${restDone.timeText.trim()}"`);
    // The four cells are checkbox w-6, status w-6, name (the only flexible
    // one) and actions w-20. So the name cell is everything the fixed columns
    // do not claim, which at any sane panel width is most of the row.
    check("the name cell is the majority of the row",
      restDone.nameWidth > restDone.rowWidth * 0.55,
      `name=${Math.round(restDone.nameWidth)} of row=${Math.round(restDone.rowWidth)}`);
    check("the running row carries the live hairline", restRunning.hasLiveHairline);
    checkActionCell(restRunning, "running, resting");

    console.log("\n== Stop asks before it acts ==");
    await page.click(`[data-testid="jobmanager-kill-${seeded.running_id}"]`);
    await page.waitForSelector(`[data-testid="jobmanager-kill-confirm-${seeded.running_id}"]`, { timeout: 5000 });
    check("Stop swaps in a confirm button", true);
    check("Stop swaps in a dismiss button",
      !!(await page.$(`[data-testid="jobmanager-kill-dismiss-${seeded.running_id}"]`)));
    check("the preview drawer did not open underneath the confirm",
      !(await page.$('[role="dialog"]')));
    checkActionCell(await measureRow(page, seeded.running_id), "running, confirming");
    await page.click(`[data-testid="jobmanager-kill-dismiss-${seeded.running_id}"]`);
    await page.waitForSelector(`[data-testid="jobmanager-kill-${seeded.running_id}"]`, { timeout: 5000 });
    check("dismissing puts the resting Stop button back", true);

    console.log("\n== the same, with the text at its largest ==");
    // The action column is rem-derived so it grows with the text while the
    // lucide icons stay at a fixed 12px -- this should have MORE headroom,
    // not less, but table-fixed means a wrong answer here is silent.
    await setAppearance({ fontScale: 1.35 });
    await page.waitForSelector(`[data-testid="jobmanager-kill-${seeded.running_id}"]`, { timeout: 30000 });
    const bigScale = await page.evaluate(() =>
      getComputedStyle(document.documentElement).fontSize);
    check("the largest text size really is applied", parseFloat(bigScale) > 20, bigScale);
    checkActionCell(await measureRow(page, seeded.running_id), "largest text, resting");
    await page.click(`[data-testid="jobmanager-kill-${seeded.running_id}"]`);
    await page.waitForSelector(`[data-testid="jobmanager-kill-confirm-${seeded.running_id}"]`, { timeout: 5000 });
    checkActionCell(await measureRow(page, seeded.running_id), "largest text, confirming");
    await page.click(`[data-testid="jobmanager-kill-dismiss-${seeded.running_id}"]`);
    await setAppearance({});

    console.log("\n== Stop, confirmed, really cancels ==");
    const killSel = `[data-testid="jobmanager-kill-${seeded.pending_id}"]`;
    await page.waitForSelector(killSel, { timeout: 30000 });
    await page.click(killSel);
    await page.click(`[data-testid="jobmanager-kill-confirm-${seeded.pending_id}"]`);
    await page.waitForSelector(`[data-testid="job-delete-${seeded.pending_id}"]`, { timeout: 20000 });
    check("the cancelled row now offers Delete instead of Stop", true);
    const backendStatus = execApi(`
from app.chemistry.jobs.base import read_status
print((read_status("${seeded.pending_id}") or {}).get("status"))
`).trim().split("\n").pop();
    check("and the backend really recorded the cancellation",
      backendStatus === "cancelled", backendStatus);

    check("no console errors during the run", consoleErrors.length === 0,
      consoleErrors.slice(0, 3).join(" | "));
  } catch (e) {
    check("spec ran without throwing", false, String(e?.stack ?? e).slice(0, 500));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    // The held job is still non-terminal, and a non-terminal job refuses to
    // be deleted -- release it before the user teardown so nothing is left
    // behind in the job list.
    if (seeded) {
      try {
        execApi(`
from app.chemistry.jobs.base import write_status
for jid in ["${seeded.running_id}", "${seeded.pending_id}"]:
    write_status(jid, "cancelled", "released by ui_16 teardown")
print("released")
`);
      } catch (e) {
        console.log(`  (cleanup) failed to release held jobs: ${String(e).slice(0, 200)}`);
      }
    }
    try {
      const cleanupPage = await adminCtx.newPage();
      const res = await cleanupPage.request.get(`${BASE_URL}/api/admin/users`);
      const found = (await res.json()).find((u) => u.username === username);
      if (found) await cleanupPage.request.delete(`${BASE_URL}/api/admin/users/${found.id}`, { headers: { Origin: BASE_URL }, timeout: 180000 });
      await cleanupPage.close();
    } catch (e) {
      console.log(`  (cleanup) failed to delete test user ${username}: ${String(e).slice(0, 200)}`);
    }
    await browser.close();
  }

  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main();
