#!/usr/bin/env node
// Pictures of the Job Manager row, for looking at rather than asserting on.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/jobrow_shots.mjs
//
// ui_16 proves the Stop button appears, fits and cancels. It cannot say
// whether the row reads well: whether the timestamp on the id line looks
// deliberate or crowded, whether the long name now fades where it used to be
// truncated by a column, or whether three controls in one cell look like a
// toolbar or a pile. So this seeds the awkward cases -- a very long name, a
// job held running, a job filed into a project so the row carries all three
// controls -- and photographs the panel in a dark theme and a light one, at
// the default text size and the largest.
//
// Not named *.spec.mjs on purpose: run_frontend.mjs runs every spec in this
// directory and this asserts nothing. It cleans up the user (and with them
// the jobs and the project) when it is done.
//
// One known rough edge, reported rather than hidden: the per-conversation
// panel sometimes cannot be photographed on a later pass, and the script says
// "(skipped)" and carries on. A thread seeded by hand has never had a chat
// turn, so the agent's own active_job_ids is legitimately empty, and both
// server/routes/chat.py and app/agent/job_watcher.py mirror that empty list
// back onto the thread whenever they run -- emptying the list this script
// wrote. It is re-asserted before every pass, which usually wins the race and
// sometimes does not. Nothing about it touches a real conversation, where the
// agent's list is the correct one. The Job Manager shots below carry the same
// row markup, so a skipped pass costs no coverage of the change itself.
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { BASE_URL, newBrowser, newContext, adminApiLogin, mintInvite } from "./_helpers.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const COMPOSE_DIR = path.resolve(HERE, "..", "..");
const OUT = path.resolve(COMPOSE_DIR, "docs", "e2e-artifacts", "jobrow");
const THREAD_LABEL = "qatest_jobrow_" + Math.random().toString(36).slice(2, 8);
const appearance = (theme, fontScale = 1) =>
  JSON.stringify({ state: { theme, accent: "hbeta", fontScale, density: "cosy", motion: "full" }, version: 0 });

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 300000,
  }).trim();
}

mkdirSync(OUT, { recursive: true });
const browser = await newBrowser();
const adminCtx = await newContext(browser);
await adminApiLogin(adminCtx);
const token = await mintInvite(adminCtx, "user");
const username = "qatest_jobrow_" + Math.random().toString(36).slice(2, 8);
const password = "correct horse battery staple 1";
const shots = [];

/** Photographs the Job Manager panel: its header plus as much of the list as
 *  it holds, found from a known row rather than from a class name. */
async function shootPanel(page, jobId, name) {
  const clip = await page.evaluate((id) => {
    const row = document.querySelector(`[data-testid="jobmanager-row-${id}"]`);
    const scroller = row.closest(".overflow-y-auto");
    const section = scroller.parentElement.parentElement;
    const r = section.getBoundingClientRect();
    return { x: Math.max(0, r.x - 4), y: Math.max(0, r.y - 4), width: r.width + 8, height: r.height + 8 };
  }, jobId);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, clip });
  shots.push(file);
  console.log(`  ${name}.png`);
}

let seeded = null;
try {
  const setup = await newContext(browser);
  const page0 = await setup.newPage();
  await page0.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
  await page0.fill('input[placeholder="Email"]', `${username}@example.test`);
  await page0.fill('input[placeholder="Username"]', username);
  await page0.fill('input[placeholder="First name"]', "QA");
  await page0.fill('input[placeholder="Last name"]', "Tester");
  await page0.fill('input[placeholder="Password"]', password);
  await page0.click('button[type="submit"]');
  await page0.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });
  await setup.close();

  const users = await (await adminCtx.request.get(`${BASE_URL}/api/admin/users`)).json();
  const user = users.find((u) => u.username === username);

  console.log("seeding...");
  seeded = JSON.parse(execApi(`
import json, time
from app.agent import threads as thread_registry
from app.auth.models import record_ownership
from app.chemistry.jobs.base import JobSpec, get_job_manager, write_meta, write_status
from app.projects import registry as project_registry

USER_ID = "${user.id}"
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
thread = thread_registry.create_thread(label="${THREAD_LABEL}")
record_ownership("thread", thread["thread_id"], USER_ID)
mgr = get_job_manager()
ids = [mgr.submit(JobSpec(task="single_point", method="hf", engine="pyscf", molecule=WATER,
                          params={"basis": "sto-3g"}), owner_user_id=USER_ID) for _ in range(3)]
long_id, running_id, filed_id = ids
write_meta(long_id, {"label": "excited state scan of a very long molecule name that nobody would sensibly type but everybody eventually does"})
write_meta(running_id, {"label": "CASSCF(8,8) on o-nitrophenol"})
write_meta(filed_id, {"label": "frequencies on benzene"})
deadline = time.time() + 280
while time.time() < deadline:
    st = {i: (mgr.status(i) or {}).get("status") for i in ids}
    if all(s in ("completed", "failed", "cancelled") for s in st.values()):
        break
    time.sleep(1.0)
thread_registry.set_active_job_ids(thread["thread_id"], [long_id, running_id])
proj = project_registry.create_project("Nitrophenol paper")
record_ownership("project", proj["project_id"], USER_ID)
project_registry.add_jobs(proj["project_id"], [filed_id])
write_status(running_id, "running", "held running for the screenshots")
print(json.dumps({"thread_id": thread["thread_id"], "long_id": long_id, "running_id": running_id,
                  "filed_id": filed_id, "project_id": proj["project_id"]}))
`).trim().split("\n").pop());
  console.log(`seeded: ${JSON.stringify(seeded)}`);

  for (const [theme, fontScale, width] of [
    ["balmer", 1, 1920], ["balmer", 1.35, 1366], ["daylight", 1, 1920],
  ]) {
    // Re-asserted every pass, not just at seed time. The job watcher mirrors
    // the agent's own active_job_ids back onto the thread whenever it runs a
    // turn for a finished job (app/agent/job_watcher.py), and a thread seeded
    // by hand has never had a chat turn, so that list is legitimately empty
    // and wipes the one written here. Real conversations are unaffected --
    // there the agent's list is the correct one.
    execApi(`
from app.agent import threads as thread_registry
thread_registry.set_active_job_ids("${seeded.thread_id}", ["${seeded.long_id}", "${seeded.running_id}"])
print("re-seeded")
`);
    const ctx = await newContext(browser);
    await ctx.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ["qc-agent-appearance", appearance(theme, fontScale)]);
    const page = await ctx.newPage();
    await page.setViewportSize({ width, height: width === 1920 ? 1080 : 900 });
    await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
    await page.fill('input[placeholder="Username or email"]', username);
    await page.fill('input[type="password"]', password);
    await page.click('[data-testid="auth-submit"]');
    await page.waitForSelector(`[data-testid="jobmanager-row-${seeded.long_id}"]`, { timeout: 30000 });
    await page.waitForTimeout(900);
    const tag = `${theme}-fs${String(fontScale).replace(".", "")}`;
    await shootPanel(page, seeded.long_id, `rows-${tag}`);

    // The per-conversation Jobs panel carries the same row shape and the same
    // change, so it gets looked at too rather than assumed to follow. Selected
    // by thread id, not by its label: the label is also the string sitting in
    // the job manager's search box, and a text= match found that one often
    // enough to make the sweep flaky. Clicking is retried and a miss is
    // reported rather than thrown -- one panel that would not open is no
    // reason to abandon the other eight pictures.
    let convOpened = false;
    for (let attempt = 0; attempt < 3 && !convOpened; attempt++) {
      await page.click(`[data-testid="conversation-row-${seeded.thread_id}"]`);
      convOpened = await page
        .waitForSelector(`[data-testid="job-row-${seeded.long_id}"]`, { timeout: 8000 })
        .then(() => true, () => false);
    }
    if (!convOpened) {
      console.log(`  (skipped) conversation-jobs-${tag}: the conversation's job list never appeared`);
    } else {
      await page.waitForTimeout(600);
      const convClip = await page.evaluate((id) => {
        const row = document.querySelector(`[data-testid="job-row-${id}"]`);
        const section = row.closest(".overflow-y-auto").parentElement.parentElement;
        const r = section.getBoundingClientRect();
        return { x: Math.max(0, r.x - 4), y: Math.max(0, r.y - 4), width: r.width + 8, height: r.height + 8 };
      }, seeded.long_id);
      const convFile = path.join(OUT, `conversation-jobs-${tag}.png`);
      await page.screenshot({ path: convFile, clip: convClip });
      shots.push(convFile);
      console.log(`  conversation-jobs-${tag}.png`);
    }

    // Mid-confirm, which is the widest the action cell ever gets.
    await page.click(`[data-testid="jobmanager-kill-${seeded.running_id}"]`);
    await page.waitForTimeout(300);
    await shootPanel(page, seeded.long_id, `confirming-${tag}`);
    await page.click(`[data-testid="jobmanager-kill-dismiss-${seeded.running_id}"]`);

    // Archived shown, which is when a row carries rename + unarchive + the
    // Kill/Delete control all at once in the wider w-28 column.
    await page.click('[data-testid="jobmanager-show-archived"]');
    await page.waitForTimeout(600);
    await shootPanel(page, seeded.long_id, `archived-${tag}`);
    await ctx.close();
  }
} finally {
  if (seeded) {
    try {
      execApi(`
from app.chemistry.jobs.base import write_status
write_status("${seeded.running_id}", "cancelled", "released by jobrow_shots teardown")
print("released")
`);
    } catch (e) { console.log(`  (cleanup) release failed: ${String(e).slice(0, 200)}`); }
  }
  try {
    // adminCtx.request, not a page's -- the admin listing comes back as a
    // bare array only on the context's own APIRequestContext here.
    const listed = await (await adminCtx.request.get(`${BASE_URL}/api/admin/users`)).json();
    const rows = Array.isArray(listed) ? listed : (listed.users || []);
    const found = rows.find((u) => u.username === username);
    if (found) {
      await adminCtx.request.delete(`${BASE_URL}/api/admin/users/${found.id}`,
        { headers: { Origin: BASE_URL }, timeout: 180000 });
      console.log(`  (cleanup) deleted ${username} and its jobs`);
    } else {
      console.log(`  (cleanup) could not find ${username} to delete: ${JSON.stringify(listed).slice(0, 200)}`);
    }
  } catch (e) { console.log(`  (cleanup) user delete failed: ${String(e).slice(0, 200)}`); }
  await browser.close();
}
console.log(`\n${shots.length} screenshots in ${OUT}`);
