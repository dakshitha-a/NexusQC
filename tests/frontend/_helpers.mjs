// Shared helpers for tests/frontend/*.spec.mjs -- raw `playwright`
// (chromium.launch), no @playwright/test runner, matching this repo's
// house style of standalone invoke-and-print scripts (see tests/README.md).
import { chromium } from "playwright";

// P4.7: was "https://127.0.0.1:8443", the standard nginx intranet port --
// every spec in this directory has always actually been run against 8444
// via QC_AGENT_TEST_BASE_URL, a leftover from when a second, offset-port
// test stack ran alongside a production one on the same host. That
// apparatus is gone, but the fallback stays 8444 since that's still what
// this suite is run against in practice; set QC_AGENT_TEST_BASE_URL
// explicitly to point it at a deployment on a different port. The stale
// fallback only ever bit a spec that omitted that env var --
// draft_01_approval_card.spec.mjs (see its own retarget below).
export const BASE_URL = process.env.QC_AGENT_TEST_BASE_URL || "https://127.0.0.1:8444";
export const ADMIN_USER = process.env.QC_AGENT_TEST_ADMIN_USER || "qatest_admin";

import { readFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CREDS_FILE = path.join(__dirname, "..", ".admin_creds");

export function adminPassword() {
  if (process.env.QC_AGENT_TEST_ADMIN_PASS) return process.env.QC_AGENT_TEST_ADMIN_PASS;
  if (existsSync(CREDS_FILE)) return readFileSync(CREDS_FILE, "utf8").trim();
  throw new Error("No admin password available -- run tests/backend/_00_bootstrap.py first.");
}

/**
 * The "this page is logged in" sentinel.
 *
 * Was `button:has-text("Log out")`, which worked only while Log out was a
 * top-level control in the account strip across the top of the shell. That
 * strip is gone -- username, account, admin and log out all live in the
 * sidebar cogwheel now -- so the sentinel is the cogwheel itself, which is
 * rendered exactly when there is a user (UserMenu returns null otherwise) and
 * needs no menu to be open.
 */
export const LOGGED_IN = '[data-testid="user-menu-open"]';

/** Open the cogwheel menu and wait for its contents. Anything asserting on
 *  Account / Admin console / Log out has to go through this first -- with the
 *  menu shut those entries are simply not in the DOM, which would quietly turn
 *  a "does a non-admin see the admin entry?" check into a tautology. */
export async function openUserMenu(page) {
  await page.click(LOGGED_IN);
  await page.waitForSelector('[data-testid="user-menu"]', { timeout: 5000 });
}

const _results = [];

export function check(name, condition, detail = "") {
  const status = condition ? "PASS" : "FAIL";
  console.log(`[${status}] ${name}${detail ? ` -- ${detail}` : ""}`);
  _results.push([name, condition, detail]);
  return condition;
}

export function summary() {
  const nFail = _results.filter(([, ok]) => !ok).length;
  console.log(`\n${_results.length - nFail}/${_results.length} checks passed in this script.`);
  return nFail === 0;
}

export async function newBrowser() {
  return chromium.launch({ ignoreHTTPSErrors: true });
}

export async function newContext(browser) {
  return browser.newContext({ ignoreHTTPSErrors: true, baseURL: BASE_URL });
}

export async function adminApiLogin(context) {
  const page = await context.newPage();
  const res = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { email_or_username: ADMIN_USER, password: adminPassword() },
    headers: { Origin: BASE_URL },
  });
  if (!res.ok()) throw new Error(`admin login failed: ${res.status()} ${await res.text()}`);
  await page.close();
}

// The stack these specs run against is also a research group's deployment.
// A spec that changes how new jobs run for everyone (cores per calculation,
// concurrency caps) checks this first and skips while any real user has the
// app open or a job in flight: anyone who does could submit into the
// changed setting. Mirrors tests/fixtures.py's jobs_refusal.
export async function realUsersActive(adminContext) {
  const res = await adminContext.request.get(`${BASE_URL}/api/admin/activity`,
    { headers: { Origin: BASE_URL } });
  const body = await res.json();
  const busy = body.users
    .filter((u) => !(u.username || "").startsWith("qatest_")
      && (u.running_jobs || u.pending_jobs || u.open_streams))
    .map((u) => `${u.username} (${u.running_jobs} running, ${u.pending_jobs} queued, ${u.open_streams} open)`);
  if (body.unowned.running_jobs || body.unowned.pending_jobs) busy.push("jobs with no owner in flight");
  return busy.length ? busy.join("; ") : null;
}

// A finished job the test admin owns, for specs that need a row to open.
// Those specs used to open whatever job the deployment held, which meant
// real users' work; since 2026-09-24 an admin sees only their own, so the
// spec brings its own. Seeds a water HF/STO-3G single point (about a second)
// only when the admin owns no job, and removes it on exit -- synchronously,
// so the specs' early process.exit() paths clean up too. Needs the docker
// stack on this host, like every other in-container shortcut in tests/.
const COMPOSE_DIR = process.env.QC_AGENT_COMPOSE_DIR
  || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function inApi(code, timeout = 180000) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code],
    { cwd: COMPOSE_DIR, encoding: "utf8", timeout }).trim().split("\n").pop();
}

export function ensureAdminJob() {
  const out = inApi(`
import time
from app.auth import models
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_spec
from app.chemistry.molecule import resolve_molecule
uid = next(str(u["id"]) for u in models.list_users() if u["username"] == ${JSON.stringify(ADMIN_USER)})
# An ownership row can outlive its job, so ask whether the job is there.
if any(read_spec(j) for j in models.list_owned("job", uid)):
    print("existing")
else:
    spec = JobSpec(task="single_point", subtype="gs", method="hf", engine="pyscf",
                   molecule=resolve_molecule("water").to_dict(), params={"basis": "sto-3g"},
                   label="qatest spec subject")
    jid = get_job_manager().submit(spec, owner_user_id=uid)
    for _ in range(120):
        if get_job_manager().status(jid)["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(1)
    print(jid)
`);
  if (out === "existing") return null;
  process.on("exit", () => {
    try {
      inApi(`
from app.auth import models
from app.chemistry.jobs.base import delete_job_dir
delete_job_dir(${JSON.stringify(out)})
models.forget_ownership("job", ${JSON.stringify(out)})
print("removed")`, 60000);
    } catch { /* the end-of-run sweep catches what this misses */ }
  });
  return out;
}

// A conversation the test admin owns with a molecule in it, for specs that
// need a molecule viewer on screen. Same reasoning as ensureAdminJob: these
// used to open whichever conversation the account could see. Built through
// the molecule-builder route the app itself uses, from a molfile RDKit
// writes in-container; removed on exit.
export async function seedMoleculeThread(context) {
  const origin = { headers: { Origin: BASE_URL } };
  const t = await (await context.request.post(`${BASE_URL}/api/threads`,
    { ...origin, data: { label: "qatest molecule subject" } })).json();
  const molblock = JSON.parse(inApi(`
import json
from rdkit import Chem
print(json.dumps(Chem.MolToMolBlock(Chem.MolFromSmiles("O"))))`, 60000));
  const r = await context.request.post(`${BASE_URL}/api/threads/${t.thread_id}/molecule/build`,
    { ...origin, data: { molblock, charge: 0, multiplicity: 1 } });
  if (!r.ok()) throw new Error(`could not build the molecule: ${r.status()} ${await r.text()}`);
  process.on("exit", () => {
    try {
      inApi(`
from app.agent import threads as t
from app.agent.graph import delete_thread_checkpoints
from app.auth import models
t.delete_thread(${JSON.stringify(t.thread_id)})
delete_thread_checkpoints(${JSON.stringify(t.thread_id)})
models.forget_ownership("thread", ${JSON.stringify(t.thread_id)})
print("removed")`, 60000);
    } catch { /* the end-of-run sweep catches what this misses */ }
  });
  return t.thread_id;
}

export function randSuffix(n = 8) {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  for (let i = 0; i < n; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

export async function mintInvite(context, role = "user") {
  const page = await context.newPage();
  const res = await page.request.post(`${BASE_URL}/api/admin/invites`, {
    data: { role },
    headers: { Origin: BASE_URL },
  });
  const body = await res.json();
  await page.close();
  return body.token;
}

export async function deleteUser(context, userId) {
  const page = await context.newPage();
  await page.request.delete(`${BASE_URL}/api/admin/users/${userId}`, { headers: { Origin: BASE_URL } });
  await page.close();
}

// Registration via the UI doesn't hand back the created user's id (the
// backend response isn't inspected by these black-box specs) -- this
// looks it up by username through the admin API for cleanup purposes.
export async function deleteUserByUsername(adminContext, username) {
  const page = await adminContext.newPage();
  const res = await page.request.get(`${BASE_URL}/api/admin/users`);
  const users = await res.json();
  // Say what went wrong rather than throwing a TypeError from cleanup. This
  // used to call .find() straight on the parsed body, so any non-list answer
  // -- a 401 whose body is {"detail": ...}, a maintenance page, a 500 --
  // surfaced as "users.find is not a function" from a helper, several frames
  // away from the spec that called it and with nothing in the message about
  // authentication. That is how draft_01 reported itself at the 2026-09 gate,
  // after every one of its own checks had passed.
  if (!Array.isArray(users)) {
    await page.close();
    throw new Error(
      `GET /api/admin/users answered ${res.status()} with ${JSON.stringify(users).slice(0, 200)}; ` +
      `expected a list of users. The admin context is probably no longer signed in.`,
    );
  }
  const found = users.find((u) => u.username === username);
  if (found) {
    await page.request.delete(`${BASE_URL}/api/admin/users/${found.id}`, { headers: { Origin: BASE_URL } });
  }
  await page.close();
  return found?.id ?? null;
}
