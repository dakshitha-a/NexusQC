// The failed-job notice renders as a card with a Troubleshoot button, and
// pressing it starts the investigation.
//
// P4.8: rewritten self-contained on the up_02_files_and_attach.spec.mjs
// pattern (register+login, seed its own state, find its own thread by the
// label it creates) instead of requiring three externally-injected env vars
// (QC_AGENT_TEST_THREAD_ID/_JOB_ID/_THREAD_LABEL) that nothing in this repo
// ever provided -- this spec was permanently unrunnable via `npm run
// test:e2e` before this rewrite, not merely undocumented. The failed job
// itself is seeded with the exact recipe tests/backend/fail_01_notice_flow.py
// already established produces "a real failed PySCF job" (an invalid basis
// set, not a near-miss -- param_normalize.normalize_basis would silently
// repair a Pople-style typo and make the job succeed, which would make this
// spec vacuous): run via `docker compose exec api python -c ...`, the same
// technique tests/backend/perf_03/04/05 already use to reach into the live
// container's own JobManager. The one addition beyond that backend recipe is
// ownership: the thread and job are explicitly recorded as owned by the
// SAME user the browser registers and logs in as (app.auth.models.
// record_ownership, mirroring exactly what POST /api/threads and
// JobManager.submit(owner_user_id=...) already do for a real user's own
// conversation), because the docker stack's auth middleware scopes
// GET /api/threads to a user's own owned threads -- an unowned thread
// created the old way (thread_registry.create_thread with no ownership
// record) would simply never appear in this user's own sidebar.
//
// The load-bearing part is the reload: the notice must survive it. A user
// who submits a long calculation and closes the tab is the normal case, not
// the edge case, so a notice that lived only in an SSE event would be
// invisible to exactly the person it is for.
//
// Unlike tests/backend/fail_01_notice_flow.py (which manually constructs a
// JobWatcher and calls _poll_once() itself, so it can intercept invoke_turn
// with a sentinel), this spec seeds the job and then simply WAITS: the live
// api container already runs its own JobWatcher polling loop (started in
// server/main.py's lifespan, _POLL_INTERVAL_SECONDS=2.0), so once the job
// reaches "failed" on disk that real, already-running watcher writes the
// notice and emits the SSE event on its own -- exactly the path a real user
// experiences, which is the whole point of testing this in a browser at all.
//
// Run against the real docker-compose dev stack (needs a rebuilt
// frontend/dist -- nginx serves it from a host bind mount, so `npm run
// build` must have run before this):
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/fail_01_notice_card.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_fail01_" + Math.random().toString(36).slice(2, 8);
const NOTICE = "text=Job failed";
const TROUBLESHOOT = 'button:has-text("Troubleshoot")';

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 220000,
  }).trim();
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_fail01_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

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

    console.log("\n== look up this user's id, for ownership recording ==");
    const usersRes = await adminCtx.request.get(`${BASE_URL}/api/admin/users`);
    const users = await usersRes.json();
    const user = users.find((u) => u.username === username);
    check("found the just-registered user via the admin API", !!user, username);

    console.log("\n== seed a real failed PySCF job, owned by this user ==");
    // Lifted verbatim from tests/backend/fail_01_notice_flow.py: an invalid
    // basis set, not a near-miss typo param_normalize.normalize_basis would
    // silently repair.
    const seedCode = `
import json, time
from app.agent import threads as thread_registry
from app.auth.models import record_ownership
from app.chemistry.jobs.base import JobSpec, get_job_manager

USER_ID = "${user.id}"
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
BOGUS_BASIS = "definitely-not-a-basis-set"

thread = thread_registry.create_thread(label="${THREAD_LABEL}")
thread_id = thread["thread_id"]
record_ownership("thread", thread_id, USER_ID)

mgr = get_job_manager()
job_id = mgr.submit(
    JobSpec(method="single_point", engine="pyscf", molecule=WATER, params={"method": "hf", "basis": BOGUS_BASIS}),
    owner_user_id=USER_ID,
)
thread_registry.set_active_job_ids(thread_id, [job_id])

deadline = time.time() + 180
status = None
while time.time() < deadline:
    status = (mgr.status(job_id) or {}).get("status")
    if status in ("completed", "failed", "cancelled"):
        break
    time.sleep(1.0)

print(json.dumps({"thread_id": thread_id, "job_id": job_id, "status": status}))
`;
    const seedOut = execApi(seedCode);
    const seeded = JSON.parse(seedOut.trim().split("\n").pop());
    console.log(`seeded: ${JSON.stringify(seeded)}`);
    check("the seeded job reached status=failed", seeded.status === "failed", seeded.status);
    const jobId = seeded.job_id;

    console.log("\n== wait for the LIVE job watcher to notice and write the card ==");
    // The real api container's own JobWatcher polls every 2s -- give it a
    // few cycles' worth of margin rather than assuming the first tick.
    await page.waitForTimeout(8000);

    console.log("\n== the notice renders as a card ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(NOTICE, { timeout: 30000 });
    check("a 'Job failed' notice card is visible", await page.isVisible(NOTICE));

    const body = await page.textContent("body");
    check("the notice names the failed job", body.includes(jobId), jobId);
    check("the notice says nothing was resubmitted",
      /haven't changed anything or resubmitted/i.test(body));

    check("a Troubleshoot button is offered", await page.isVisible(TROUBLESHOOT));

    console.log("\n== the notice survives a reload ==");
    // The whole reason jobs run detached is that a user can leave and come
    // back. A notice that did not survive this would be invisible to the
    // person most likely to hit a failure.
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(NOTICE, { timeout: 30000 });
    check("the notice is still there after a full page reload",
      await page.isVisible(NOTICE));
    check("the Troubleshoot button is still offered after reload",
      await page.isVisible(TROUBLESHOOT));

    console.log("\n== pressing Troubleshoot starts the investigation ==");
    const [response] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes(`/troubleshoot/${jobId}`) && r.request().method() === "POST",
        { timeout: 20000 },
      ),
      page.click(TROUBLESHOOT),
    ]);
    check("the troubleshoot route was called", response.status() === 202,
      `status ${response.status()}`);
    // The button is replaced by a progress line: the action is one-shot,
    // so a user cannot fire three investigations by clicking three times.
    await page.waitForSelector("text=Looking at the engine's output", { timeout: 15000 });
    check("the card shows the investigation has started",
      await page.isVisible("text=Looking at the engine's output"));
    check("the Troubleshoot button is no longer offered (one-shot)",
      !(await page.isVisible(TROUBLESHOOT)));

    console.log("\n== no console errors ==");
    // GET /api/auth/me 401s once, harmlessly, before login on every
    // anonymous page load (see up_02_files_and_attach.spec.mjs's own
    // comment on this) -- filtered by status TEXT, not URL, because
    // Chrome's own "Failed to load resource" console line carries no URL
    // at all (confirmed empirically: a URL-based filter let this exact
    // 401 straight through as an unexpected error on the first run of
    // this spec).
    const real = consoleErrors.filter(
      (t) => !/status of 401/i.test(t) && !/favicon/i.test(t),
    );
    check("no console errors beyond the known environmental ones",
      real.length === 0, real.slice(0, 3).join(" | "));
  } catch (e) {
    check("spec ran without throwing", false, String(e?.stack ?? e).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    // A generous timeout and a try/catch, not the shared helper's default:
    // clicking Troubleshoot starts a REAL background agent turn (a live
    // LLM call, per app/agent/troubleshoot.py -- the POST returns 202
    // immediately and the turn keeps running under the graph's own lock),
    // and deleting a user while their conversation is still mid-turn can
    // legitimately take longer than Playwright's 30s default request
    // timeout waiting on that same lock. This is test cleanup, not
    // something the spec exists to verify -- a slow or failed cleanup
    // must never crash the process before summary()/process.exit() report
    // the actual results above.
    try {
      const cleanupPage = await adminCtx.newPage();
      const usersRes = await cleanupPage.request.get(`${BASE_URL}/api/admin/users`);
      const found = (await usersRes.json()).find((u) => u.username === username);
      if (found) {
        await cleanupPage.request.delete(`${BASE_URL}/api/admin/users/${found.id}`, { timeout: 180000 });
      }
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
