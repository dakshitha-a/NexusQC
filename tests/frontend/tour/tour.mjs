#!/usr/bin/env node
// Films the README's animations into docs/tour/, one function per scene.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/tour/tour.mjs hero asks ...
//   node tests/frontend/tour/tour.mjs probe-hero      # check the hero prompt, film nothing
//
// Each scene follows its row of the storyboard in docs/TESTING.md ("The
// README's animations"): what happens, and where the camera looks while it
// does. The scene only says "look here" and "pull back"; animate.py moves
// the camera and cuts the frames.
//
// It films the real app on a live stack, as the test admin, whose sidebar
// and job list start empty. The stack may have real users on it, so the run
// snapshots the account's conversations, jobs, plots and projects first and
// deletes only what is new at the end, whatever happened in between. Jobs
// the scenes need finished are seeded in the api container through
// JobManager.submit with the admin as owner: a job with no owner would show
// in every user's list.
//
// Run by hand, since it writes into docs/tour/. It is not a *.spec.mjs, so
// run_frontend.mjs never picks it up.
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { BASE_URL, ADMIN_USER, adminPassword, LOGGED_IN } from "../_helpers.mjs";
import { Recorder, glide, span, typeOut } from "./recorder.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..", "..");
const OUT = path.join(REPO, "docs", "tour");
// Outside the repository: a scene's raw frames run to hundreds of megabytes.
const FRAMES = process.env.QC_AGENT_TOUR_FRAMES || path.join(tmpdir(), "nexusqc-tour-frames");
const PYTHON = process.env.QC_AGENT_TOUR_PYTHON || "python3";
// Twice the window's pixels, so a close-up is cut from real pixels. It has
// to be the browser's own ratio, given at launch, as well as the page's: the
// screencast sends frames at the compositor's size and ignores the ratio a
// context emulates (found in NextTex, where every clip had been filmed at 1).
const DPR = Number(process.env.QC_AGENT_TOUR_DPR ?? 2);
const VIEW = { width: 1600, height: 950 };
const ORIGIN = { headers: { Origin: BASE_URL } };
const APPEARANCE_KEY = "qc-agent-appearance";

// The hero's request names everything the app would otherwise ask for, so
// it reaches the approval card in one turn.
const HERO_PROMPT =
  "Compute the UV/Vis spectrum of formaldehyde with full TDDFT, B3LYP/def2-SVP, 6 singlet excited states with oscillator strengths, on PySCF";

// --- the api container ------------------------------------------------------

function inApi(code, timeout = 600000) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code],
    { cwd: REPO, encoding: "utf8", timeout }).trim().split("\n").pop();
}

function adminId() {
  return inApi(`
from app.auth import models
print(next(str(u["id"]) for u in models.list_users() if u["username"] == ${JSON.stringify(ADMIN_USER)}))`, 60000);
}

/** Submit jobs as the admin and wait for every one to finish. `specs` is a
 *  Python expression for a list of (label, JobSpec) pairs. Returns
 *  {label: job id}. */
function seedJobs(specs, waitS = 600) {
  return JSON.parse(inApi(`
import json, time
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.chemistry.molecule import resolve_molecule
mgr = get_job_manager()
uid = ${JSON.stringify(adminId())}
ids = {k: mgr.submit(s, owner_user_id=uid) for k, s in ${specs}}
deadline = time.time() + ${waitS}
while time.time() < deadline:
    st = {k: (mgr.status(j) or {}).get("status") for k, j in ids.items()}
    if all(s in ("completed", "failed", "cancelled") for s in st.values()):
        break
    time.sleep(1)
print(json.dumps({"ids": ids, "status": st}))`));
}

// --- what the account holds, before and after -------------------------------

// The app keeps one session per account, so logging the browser in ends any
// earlier API session. Each inventory therefore logs in afresh, and a list
// that does not answer 200 stops the run rather than reading as empty: an
// empty "after" would make every leftover look already cleaned.
async function freshApi(browser) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  const r = await ctx.request.post(`${BASE_URL}/api/auth/login`, {
    ...ORIGIN, data: { email_or_username: ADMIN_USER, password: adminPassword() },
  });
  if (!r.ok()) throw new Error(`login failed: ${r.status()}`);
  return ctx.request;
}

async function inventory(api) {
  const list = async (url, idKey) => {
    const r = await api.get(`${BASE_URL}${url}`);
    if (!r.ok()) throw new Error(`${url} answered ${r.status()}`);
    return new Set((await r.json()).map((row) => row[idKey]));
  };
  return {
    threads: await list("/api/threads", "thread_id"),
    jobs: await list("/api/jobs?include_archived=true", "job_id"),
    plots: await list("/api/plots", "plot_id"),
    projects: await list("/api/projects", "project_id"),
  };
}

async function cleanUp(browser, before) {
  const api = await freshApi(browser);
  const after = await inventory(api);
  const fresh = (k) => [...after[k]].filter((id) => !before[k].has(id));
  const gone = { projects: 0, plots: 0, jobs: 0, threads: 0 };
  // Projects first and with their results, or the jobs inside survive them.
  for (const id of fresh("projects")) {
    if ((await api.delete(`${BASE_URL}/api/projects/${id}?delete_jobs=true`, ORIGIN)).ok()) gone.projects++;
  }
  for (const id of fresh("plots")) {
    if ((await api.delete(`${BASE_URL}/api/plots/${id}`, ORIGIN)).ok()) gone.plots++;
  }
  for (const id of fresh("jobs")) {
    await api.post(`${BASE_URL}/api/jobs/${id}/cancel`, ORIGIN).catch(() => undefined);
    if ((await api.delete(`${BASE_URL}/api/jobs/${id}`, ORIGIN)).ok()) gone.jobs++;
  }
  for (const id of fresh("threads")) {
    if ((await api.delete(`${BASE_URL}/api/threads/${id}`, ORIGIN)).ok()) gone.threads++;
  }
  const left = await inventory(api);
  const leftover = Object.fromEntries(Object.keys(left).map((k) => [k, [...left[k]].filter((id) => !before[k].has(id))]));
  console.log(`cleaned up ${JSON.stringify(gone)}; left behind ${JSON.stringify(leftover)}`);
  return leftover;
}

// --- the app ------------------------------------------------------------------

async function openApp(browser, theme = "nightshift") {
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true, baseURL: BASE_URL, viewport: VIEW, deviceScaleFactor: DPR,
  });
  await ctx.addInitScript(([k, v]) => localStorage.setItem(k, v), [APPEARANCE_KEY, JSON.stringify({
    state: { theme, accent: "hbeta", fontScale: 1, density: "cosy", motion: "full" }, version: 0,
  })]);
  const page = await ctx.newPage();
  await Recorder.install(page);
  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
  await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
  await page.fill('input[type="password"]', adminPassword());
  await page.click('[data-testid="auth-submit"]');
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  // The "new here?" tutorial banner is for a first visit, not for a demo.
  const dismiss = page.locator('button[aria-label*="ismiss"]').first();
  if (await dismiss.isVisible().catch(() => false)) await dismiss.click();
  return { ctx, page };
}

async function newThread(page, label) {
  const t = await (await page.request.post(`${BASE_URL}/api/threads`, { ...ORIGIN, data: { label } })).json();
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await page.click(`[data-testid="conversation-row-${t.thread_id}"]`);
  await page.waitForTimeout(600);
  return t.thread_id;
}

async function jobStatus(page, id) {
  const r = await page.request.get(`${BASE_URL}/api/jobs/${id}`);
  return r.ok() ? (await r.json()).status : null;
}

async function untilJobDone(page, id, timeoutMs = 600000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const s = await jobStatus(page, id);
    if (["completed", "failed", "cancelled"].includes(s)) return s;
    await page.waitForTimeout(1000);
  }
  throw new Error(`job ${id} did not finish`);
}

/** The id the chat prints once a job starts. */
async function startedJobId(page, timeoutMs = 60000) {
  const el = page.locator("text=/Job id\\s+[0-9a-f]{6,}/").last();
  await el.waitFor({ timeout: timeoutMs });
  return (await el.textContent()).match(/Job id\s+([0-9a-f]{6,})/)[1];
}

function animate(name, file, width = 960, extra = []) {
  const out = path.join(OUT, file);
  console.log(execFileSync(PYTHON, [path.join(HERE, "animate.py"), path.join(FRAMES, name), out, "--width", String(width), ...extra],
    { encoding: "utf8" }).trim());
}

const composer = (page) => page.locator('[data-testid="chat-composer"]');

// --- scenes ---------------------------------------------------------------------

/** H: a sentence becomes a real calculation. Request, approval card with the
 *  input it will run, approve, the job finishes, the result opens. */
async function hero(page, { theme = "nightshift" } = {}) {
  await newThread(page, "Formaldehyde UV/Vis, TDDFT");
  await page.mouse.move(800, 600);
  const name = `hero-${theme === "daylight" ? "light" : "dark"}`;
  const rec = new Recorder(page, name, FRAMES);
  await rec.start();
  await rec.hold(600);

  const box = composer(page);
  await glide(page, box);
  await box.click();
  await rec.focus(box, { pad: 120 });
  await typeOut(box, HERO_PROMPT);
  await rec.hold(400);
  await box.press("Enter");
  rec.wide();

  const approve = page.locator('[data-testid="approval-approve"]');
  await rec.quickly(() => approve.waitFor({ timeout: 300000 }), 8);
  const card = approve.locator("xpath=ancestor::div[contains(@class,'rounded')][1]");
  await rec.hold(300);
  await rec.focus(await card.boundingBox() ? card : approve, { pad: 30 });
  await rec.hold(3200);

  await glide(page, approve);
  await rec.hold(300);
  await approve.click();
  const jobId = await startedJobId(page);
  const row = page.locator(`[data-testid="job-row-${jobId}"]`);
  await row.waitFor({ timeout: 30000 });
  await rec.focus(row, { pad: 90 });
  await rec.quickly(() => untilJobDone(page, jobId), 10);
  await rec.hold(1200);

  await glide(page, row);
  await row.click();
  const drawer = page.locator('[role="dialog"]');
  await drawer.waitFor({ timeout: 20000 });
  await rec.hold(500);
  rec.wide(0.9);
  await rec.hold(1500);
  // The spectrum sits below the states table; scroll the drawer to it and
  // end the clip there, since it is the answer to what was asked.
  // A finished spectrum job carries the server-rendered PNG (UvVisPanel);
  // the inline chart is only the fallback for a job without one.
  const chart = drawer.locator('img[alt="UV/Vis spectrum"]').first();
  await chart.waitFor({ timeout: 30000 });
  await chart.evaluate((el) => el.scrollIntoView({ behavior: "smooth", block: "center" }));
  await page.waitForFunction((el) => el.complete && el.naturalWidth > 0, await chart.elementHandle());
  await rec.hold(900);
  await rec.focus(chart, { pad: 24 });
  await rec.hold(4000);
  rec.wide();
  await rec.hold(800);
  await rec.stop();
  animate(name, `${name}.webp`, 1280);
}

/** Runs the hero's request without filming and says how it went: did it
 *  reach the approval card, and did the card auto-correct anything. */
async function probeHero(page) {
  await newThread(page, "probe hero");
  const t0 = Date.now();
  await composer(page).fill(HERO_PROMPT);
  await composer(page).press("Enter");
  const approve = page.locator('[data-testid="approval-approve"]');
  const reply = page.locator('[data-testid="agent-thinking"]');
  try {
    await approve.waitFor({ timeout: 300000 });
  } catch {
    console.log(`[probe] no card after ${(Date.now() - t0) / 1000}s`);
    return false;
  }
  const corrected = await page.locator("text=/Auto-corrected/").count();
  const head = await page.locator("text=/^Approve /").first().textContent().catch(() => "?");
  console.log(`[probe] card after ${((Date.now() - t0) / 1000).toFixed(0)}s: "${head}", auto-corrected banners: ${corrected}`);
  await page.locator('[data-testid="approval-reject"]').click();
  void reply;
  return true;
}

const SCENES = {
  hero: (p) => hero(p),
  "hero-light": null, // filmed in its own context, below
  "probe-hero": probeHero,
};

// --- main -------------------------------------------------------------------------

const wanted = process.argv.slice(2);
if (!wanted.length || wanted.some((w) => !(w in SCENES))) {
  console.log(`usage: tour.mjs <scene ...>; scenes: ${Object.keys(SCENES).join(", ")}`);
  process.exit(2);
}

const browser = await chromium.launch({ args: [`--force-device-scale-factor=${DPR}`] });
const before = await inventory(await freshApi(browser));
let failed = false;
try {
  for (const w of wanted) {
    console.log(`== ${w}`);
    const theme = w === "hero-light" ? "daylight" : "nightshift";
    const { ctx, page } = await openApp(browser, theme);
    try {
      if (w === "hero-light") await hero(page, { theme });
      else await SCENES[w](page);
    } catch (e) {
      failed = true;
      console.log(`[FAIL] ${w}: ${e.stack || e}`);
    } finally {
      await ctx.close();
    }
  }
} finally {
  const leftover = await cleanUp(browser, before);
  await browser.close();
  if (Object.values(leftover).some((v) => v.length)) failed = true;
}
process.exit(failed ? 1 : 0);
