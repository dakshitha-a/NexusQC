// The admin panel's Deployment section, in a real browser.
//
// It is new rendering, not old rendering with a check bolted on, so what this
// has to prove is that it draws at all -- a section that throws on mount looks
// identical to one that renders empty if you only assert on the routes behind
// it, and both look fine in a code read.
//
// Four things, in the order an admin meets them:
//
//   1. The nav entry exists and the section mounts when clicked.
//   2. It reports the API's commit, and that commit is the same one
//      /api/version reports -- proving the number on screen came from the
//      deployment rather than from a placeholder.
//   3. It reports this tab's own build sha, baked into the bundle at build
//      time, and does not claim a mismatch when the two agree. Telling an
//      admin to reload when nothing has changed is the failure mode here.
//   4. The "who is working right now" table reflects reality: with a running
//      job staged against the admin, their row appears with the job counted;
//      with it gone, the section says nobody would be interrupted.
//
// The staged job is written directly rather than computed, for the reason
// tests/backend/deploy_04_deployment_activity.py records at length: on this
// host a real single point finishes in under two seconds, so polling for one
// tests how fast PySCF is rather than whether the panel reads the job files.
//
// Needs a rebuilt frontend/dist, because nginx serves it from a host bind
// mount and `docker compose build` will not refresh it:
//
//   cd frontend && npm run build
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/deploy_05_deployment_section.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, openUserMenu, check, summary, BASE_URL, LOGGED_IN,
} from "./_helpers.mjs";

const COMPOSE_DIR = process.env.QC_AGENT_COMPOSE_DIR
  || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function apiPython(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code],
    { cwd: COMPOSE_DIR, encoding: "utf8", timeout: 60000 }).trim();
}

async function main() {
  const browser = await newBrowser();
  const ctx = await newContext(browser);
  await adminApiLogin(ctx);

  // The commit the deployment reports about itself, read before the browser
  // is involved, so the number the panel prints can be compared against
  // something this spec did not get from the panel.
  const verRes = await ctx.request.get(`${BASE_URL}/api/version`);
  const apiCommit = (await verRes.json()).commit;
  check("/api/version answers with a commit", Boolean(apiCommit), String(apiCommit));

  const page = await ctx.newPage();
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });

  await openUserMenu(page);
  await page.click('text=Admin console');
  await page.waitForSelector('[data-testid="admin-nav-deployment"]', { timeout: 10000 });
  check("the Deployment nav entry is rendered in the admin panel", true);

  await page.click('[data-testid="admin-nav-deployment"]');
  await page.waitForSelector('text=What is running', { timeout: 10000 });
  check("the Deployment section mounts and draws its first heading", true);

  // 2 + 3: the two commits, on screen.
  await page.waitForSelector('text=Who is working right now', { timeout: 10000 });
  const bodyText = await page.textContent("body");
  const short = apiCommit.slice(0, 12);
  check(
    "the section prints the API commit the deployment actually reports",
    bodyText.includes(short),
    `looking for ${short}`,
  );
  check(
    "it labels one of them as this browser tab's own build",
    bodyText.includes("This browser tab"),
    "",
  );
  // The bundle and the api were built together here, so the panel must NOT be
  // telling the admin to reload.
  check(
    "with the tab and the server in step, no stale-build warning is shown",
    !bodyText.includes("older build than the server"),
    "a reload prompt appeared when both commits agree",
  );

  // 4a: the table agrees with the API it is drawn from.
  //
  // This deliberately does NOT assert that the deployment is idle. It is a
  // real multi-user deployment and somebody else may genuinely have the app
  // open -- when this check was first written as "idle", it failed because
  // another user's browser held a live event stream, and the panel was right.
  // Asserting correspondence instead is both true whatever the deployment is
  // doing and a stronger claim than either fixed expectation: the rendering
  // has to match the numbers, not merely be non-empty.
  //
  // "Idle" also has to mean "nobody ELSE": opening this page is itself an open
  // stream, so an admin always appears in their own activity table. A panel
  // that permanently claims somebody is mid-calculation trains people to click
  // through the warning that matters.
  const actRes = await ctx.request.get(`${BASE_URL}/api/admin/activity`);
  const act = await actRes.json();
  const others = act.totals.others_interrupted;

  if (others === 0 && act.totals.running_jobs === 0) {
    check(
      "with nobody else working, the section says restarting interrupts no one",
      bodyText.includes("Restarting now interrupts no one"),
      `others_interrupted=${others}`,
    );
  } else {
    check(
      "with somebody else working, the section names them instead of claiming it is idle",
      !bodyText.includes("Restarting now interrupts no one")
        && act.users.filter((u) => u.would_be_interrupted && !u.is_you)
             .every((u) => bodyText.includes(u.username)),
      `others_interrupted=${others}: ` +
        act.users.filter((u) => u.would_be_interrupted && !u.is_you).map((u) => u.username).join(", "),
    );
  }
  check(
    "the counters on screen match the ones the API reports",
    bodyText.includes(`${act.totals.running_jobs}running jobs`)
      && bodyText.includes(`${act.totals.pending_jobs}queued jobs`)
      && bodyText.includes(`${act.totals.open_streams}open streams`),
    `api totals: ${JSON.stringify(act.totals)}`,
  );

  // 4b: stage a running job owned by the admin and watch the table change.
  const adminId = apiPython(
    "from app.auth.models import list_users\n" +
    "print(next(str(u['id']) for u in list_users() if u['role'] == 'admin'))\n"
  ).split("\n").pop().trim();

  const jobId = apiPython(
    "import json, uuid, time\n" +
    "from pathlib import Path\n" +
    "from app.config import JOBS_DIR\n" +
    "from app.auth.models import record_ownership\n" +
    "jid = 'qatest' + uuid.uuid4().hex[:6]\n" +
    "d = Path(JOBS_DIR) / jid; d.mkdir(parents=True)\n" +
    "(d / 'spec.json').write_text(json.dumps({'job_id': jid, 'task': 'single_point', 'subtype': 'gs',\n" +
    "    'method': 'hf', 'engine': 'pyscf', 'molecule': {}, 'params': {}}))\n" +
    "(d / 'status.json').write_text(json.dumps({'status': 'running', 'message': 'qatest probe',\n" +
    "    'updated_at': time.time()}))\n" +
    `record_ownership('job', jid, '${adminId}')\n` +
    "print(jid)\n"
  ).split("\n").pop().trim();

  let sawBusy = false;
  try {
    // The section polls every 5s, so this is waiting for its own refresh
    // rather than for a page reload -- which is also the assertion that the
    // polling works.
    await page.waitForSelector("text=1 running", { timeout: 20000 });
    sawBusy = true;
  } catch { /* reported by the check below */ }
  check(
    "a running job appears in the table without reloading the page",
    sawBusy,
    "the section never showed the staged job within 20s",
  );

  if (sawBusy) {
    const busyText = await page.textContent("body");
    check(
      "and the idle message is gone while somebody would be interrupted",
      !busyText.includes("Restarting now interrupts no one"),
      "",
    );
  }

  // Cleanup: the staged job, and nothing else.
  apiPython(
    "import shutil\n" +
    "from pathlib import Path\n" +
    "from app.config import JOBS_DIR\n" +
    `shutil.rmtree(Path(JOBS_DIR) / '${jobId}', ignore_errors=True)\n` +
    "print('removed')\n"
  );
  check("the staged job was cleaned up", true, jobId);

  await browser.close();
  summary();
}

main().catch((e) => { console.error(e); process.exit(1); });
