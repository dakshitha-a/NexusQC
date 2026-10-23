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

/** A single-geometry PySCF job, as a JobSpec expression. */
const pyscfJob = (label, task, subtype, method, molecule, params) =>
  `(${JSON.stringify(label)}, JobSpec(task=${JSON.stringify(task)}, subtype=${JSON.stringify(subtype)}, ` +
  `method=${JSON.stringify(method)}, engine="pyscf", molecule=resolve_molecule(${JSON.stringify(molecule)}).to_dict(), ` +
  `params=${JSON.stringify(params).replace(/true/g, "True").replace(/false/g, "False")}))`;

/** A nuclear-ensemble spectrum, seeded the way submit_draft starts one:
 *  a frequency job, then samples drawn from it and handed to
 *  submit_ensemble. A wigner_spectra spec given to plain submit() fails at
 *  dispatch, since the ensemble is orchestrated rather than run. */
function seedEnsemble(molecule, nSamples = 16) {
  return JSON.parse(inApi(`
import json, random, time
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_spec
from app.chemistry.jobs.wigner import sample_from_source_job
from app.chemistry.molecule import resolve_molecule
mgr = get_job_manager()
uid = ${JSON.stringify(adminId())}
lot = {"basis": "def2-svp", "functional": "b3lyp"}
f = mgr.submit(JobSpec(task="freq", subtype="", method="dft", engine="pyscf",
                       molecule=resolve_molecule(${JSON.stringify(molecule)}).to_dict(), params=lot), owner_user_id=uid)
while mgr.status(f)["status"] not in ("completed", "failed", "cancelled"):
    time.sleep(1)
m = read_spec(f)["molecule"]
seed = random.randint(0, 2**31 - 1)
params = {**lot, "n_states": 4, "n_excited_states": 4, "n_samples": ${nSamples}, "random_seed": seed,
          "temperature_K": 0.0, "want_oscillator_strengths": True, "source_frequency_job_id": f}
samples, diag = sample_from_source_job(m, mgr.result(f)["summary"], n_samples=${nSamples}, random_seed=seed)
w = mgr.submit_ensemble(JobSpec(task="wigner_spectra", subtype="", method="dft", engine="pyscf",
                                molecule=m, params=params), samples, diag, owner_user_id=uid)
deadline = time.time() + 900
while time.time() < deadline and mgr.status(w)["status"] not in ("completed", "failed", "cancelled"):
    time.sleep(2)
print(json.dumps({"freq": f, "ensemble": w, "status": mgr.status(w)["status"]}))`));
}

/** A job that fails for a reason a chemist would recognise, attached to a
 *  conversation so the chat shows its failure card. The v2 JobSpec shape
 *  matters: fail_01's pre-v2 shape fails at dispatch with "No runner is
 *  wired up", which is not the story this scene tells. */
function seedFailedJob(threadId) {
  return JSON.parse(inApi(`
import json, time
from app.agent import threads as thread_registry
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.chemistry.molecule import resolve_molecule
mgr = get_job_manager()
uid = ${JSON.stringify(adminId())}
j = mgr.submit(JobSpec(task="single_point", subtype="gs", method="dft", engine="pyscf",
                       molecule=resolve_molecule("water").to_dict(),
                       params={"basis": "def2-tzvpp-typo", "functional": "b3lyp"}), owner_user_id=uid)
while mgr.status(j)["status"] not in ("completed", "failed", "cancelled"):
    time.sleep(1)
thread_registry.set_active_job_ids(${JSON.stringify(threadId)}, [j])
print(json.dumps({"job": j, "status": mgr.status(j)["status"]}))`));
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

/** A logged-in page on a conversation of its own, named `label`. The
 *  conversation is made before the browser logs in: an account with none
 *  gets an empty "New conversation" made for it on load, which would sit in
 *  the sidebar of every clip. */
async function openApp(browser, { theme = "nightshift", label }) {
  const api = await freshApi(browser);
  const threadId = (await (await api.post(`${BASE_URL}/api/threads`, { ...ORIGIN, data: { label } })).json()).thread_id;
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true, baseURL: BASE_URL, viewport: VIEW, deviceScaleFactor: DPR,
  });
  await ctx.addInitScript(([k, v]) => localStorage.setItem(k, v), [APPEARANCE_KEY, JSON.stringify({
    state: { theme, accent: "hbeta", fontScale: 1, density: "cosy", motion: "full" }, version: 0,
  })]);
  // An update's "NexusQC was updated" banner stays for an hour; filmed
  // straight after a deploy it would sit across the top of every clip.
  const notice = (await (await api.get(`${BASE_URL}/api/notice`)).json()).notice;
  if (notice) {
    await ctx.addInitScript((v) => localStorage.setItem("nexusqc.notice.dismissed", v), `${notice.id}:${notice.phase}`);
  }
  const page = await ctx.newPage();
  await Recorder.install(page);
  await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
  await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
  await page.fill('input[type="password"]', adminPassword());
  await page.click('[data-testid="auth-submit"]');
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  // The "new here?" tutorial banner is for a first visit, not for a demo.
  const hint = page.locator('[data-testid="first-run-hint-dismiss"]');
  if (await hint.isVisible().catch(() => false)) await hint.click();
  await page.click(`[data-testid="conversation-row-${threadId}"]`);
  await page.waitForTimeout(600);
  return { ctx, page, threadId };
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

/** Wait for the agent's turn to finish: the Thinking indicator has come and
 *  gone, and stayed gone for a moment, since a turn that calls several tools
 *  shows it more than once. */
async function turnDone(page, timeoutMs = 300000) {
  const thinking = page.locator('[data-testid="agent-thinking"]');
  // The send button is swapped for Stop while the turn runs. The thinking
  // line alone is not enough: it goes away while a reply streams, and on a
  // loaded host a long reply streamed for over the quiet period.
  const send = page.locator('[data-testid="chat-send"]');
  await thinking.first().waitFor({ timeout: 15000 }).catch(() => undefined);
  const end = Date.now() + timeoutMs;
  let quietSince = 0;
  while (Date.now() < end) {
    if ((await thinking.count()) || !(await send.count())) quietSince = 0;
    else if (!quietSince) quietSince = Date.now();
    else if (Date.now() - quietSince > 2500) return;
    await page.waitForTimeout(250);
  }
  throw new Error("the agent's turn did not finish");
}

const lastReply = (page) => page.locator("div.justify-start > div.rounded-bl-sm").last();

/** Open a job's detail drawer from the Job Manager list. */
async function openFromManager(page, rec, jobId) {
  const row = page.locator(`[data-testid="jobmanager-row-${jobId}"]`);
  await row.waitFor({ timeout: 30000 });
  await glide(page, row);
  await rec.hold(200);
  await row.click();
  const drawer = page.locator('[role="dialog"]');
  await drawer.waitFor({ timeout: 20000 });
  return drawer;
}

/** Move a range input to a value, in steps, the way a dragged thumb does.
 *  React's own value setter and an input event, since fill() does not
 *  drive a range input (ui_10_atom_label_toggle found this). */
async function slide(page, input, to, steps = 14, pauseMs = 70) {
  const from = Number(await input.inputValue());
  for (let i = 1; i <= steps; i++) {
    const v = from + ((to - from) * i) / steps;
    await input.evaluate((el, val) => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      set.call(el, String(val));
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }, v);
    await page.waitForTimeout(pauseMs);
  }
}

async function say(page, rec, text) {
  const box = composer(page);
  await glide(page, box);
  await box.click();
  await typeOut(box, text);
  await rec.hold(350);
  await box.press("Enter");
}

// --- scenes ---------------------------------------------------------------------

/** H: a sentence becomes a real calculation. Request, approval card with the
 *  input it will run, approve, the job finishes, the result opens. */
async function hero(page, { theme = "nightshift" } = {}) {
  await page.mouse.move(800, 600);
  const name = `hero-${theme === "daylight" ? "light" : "dark"}`;
  const rec = new Recorder(page, name, FRAMES);
  await rec.start();
  // Every clip opens on where its action is, not the whole window: at the
  // README's width the whole window is too small to read, and the first
  // frame is the one a reader sees before anything moves.
  const box = composer(page);
  await rec.focus(box, { pad: 120, ease: 0 });
  await rec.hold(600);
  await glide(page, box);
  await box.click();
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

/** 1: it asks instead of guessing. A CASSCF request with no basis and no
 *  active space gets a question back, and nothing is submitted. */
async function asks(page) {
  await page.mouse.move(800, 600);
  const rec = new Recorder(page, "asks", FRAMES);
  await rec.start();
  await rec.focus(composer(page), { pad: 160, ease: 0 });
  await rec.hold(500);
  await say(page, rec, "Run a CASSCF single point on formaldehyde");
  await rec.quickly(() => turnDone(page), 6);
  const reply = lastReply(page);
  await rec.focus(reply, { pad: 40 });
  await rec.hold(5000);
  rec.wide();
  await rec.hold(900);
  await rec.stop();
  animate("asks", "asks.webp");
}

/** 2: a molecule from one word, in 3D with numbered atoms. */
async function molecule(page) {
  await page.mouse.move(800, 600);
  const rec = new Recorder(page, "molecule", FRAMES);
  await rec.start();
  await rec.focus(composer(page), { pad: 160, ease: 0 });
  await rec.hold(500);
  await say(page, rec, "caffeine");
  const pane = page.locator('[data-testid="section-molecule-panel"]');
  const canvas = pane.locator("canvas").first();
  await rec.quickly(() => canvas.waitFor({ timeout: 120000 }), 6);
  await rec.quickly(() => turnDone(page), 6);
  await rec.focus(pane, { pad: 10 });
  await rec.hold(1400);
  // Turn it by hand.
  const box = await canvas.boundingBox();
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  await page.mouse.move(cx - 60, cy, { steps: 10 });
  await page.mouse.down();
  await page.mouse.move(cx + 90, cy + 25, { steps: 40 });
  await page.mouse.up();
  await rec.hold(800);
  // Numbers off for a clean picture, and back on.
  const labels = page.locator('[data-testid="molecule-atom-labels"]');
  await glide(page, labels);
  await labels.click();
  await rec.hold(2400);
  await labels.click();
  await rec.hold(2000);
  rec.wide();
  await rec.hold(800);
  await rec.stop();
  animate("molecule", "molecule.webp");
}

/** 3: orbitals on a finished job. HOMO, then LUMO, then the isovalue. */
async function orbitals(page) {
  const seeded = seedJobs(`[${pyscfJob("benzene", "single_point", "gs", "hf", "benzene", { basis: "6-31g*" })}]`);
  const jobId = seeded.ids.benzene;
  await page.reload({ waitUntil: "networkidle" });
  await page.mouse.move(800, 600);
  const rec = new Recorder(page, "orbitals", FRAMES);
  await rec.start();
  await rec.focus(page.locator(`[data-testid="jobmanager-row-${jobId}"]`), { pad: 90, ease: 0 });
  await rec.hold(500);
  const drawer = await openFromManager(page, rec, jobId);
  const rows = drawer.locator('[data-testid^="orbital-row-"]');
  await rows.first().waitFor({ timeout: 30000 });
  // The HOMO is the last occupied row; the LUMO is the one after it.
  const homoAt = await rows.evaluateAll((trs) =>
    trs.map((tr) => Number(tr.children[2]?.textContent)).reduce((last, occ, i) => (occ > 0 ? i : last), -1));
  const homo = rows.nth(homoAt), lumo = rows.nth(homoAt + 1);
  await homo.scrollIntoViewIfNeeded();
  await rec.hold(500);
  await rec.focus(await span(rows.nth(Math.max(0, homoAt - 3)), rows.nth(homoAt + 3)), { pad: 30 });
  await glide(page, homo);
  await homo.click();
  const iso = drawer.locator('[data-testid="mocube-isoval"]');
  await rec.quickly(() => iso.waitFor({ timeout: 90000 }), 4);
  const viewer = iso.locator("xpath=ancestor::div[.//canvas][1]");
  await viewer.scrollIntoViewIfNeeded();
  await rec.hold(1200);
  await rec.focus(viewer, { pad: 16 });
  await rec.hold(2200);
  await lumo.scrollIntoViewIfNeeded();
  await glide(page, lumo);
  await lumo.click();
  await rec.quickly(() => page.waitForTimeout(4000), 3);
  await viewer.scrollIntoViewIfNeeded();
  await rec.focus(viewer, { pad: 16 });
  await rec.hold(2000);
  await glide(page, iso);
  const start = Number(await iso.inputValue());
  // Each step redraws the isosurface, which takes a moment, so few steps.
  await slide(page, iso, start * 2, 5, 40);
  await rec.hold(1200);
  await slide(page, iso, start * 0.6, 6, 40);
  await rec.hold(1800);
  rec.wide();
  await rec.hold(800);
  await rec.stop();
  animate("orbitals", "orbitals.webp");
}

/** 4: a nuclear-ensemble spectrum, re-broadened live and zoomed to a band. */
async function spectrum(page) {
  const seeded = seedEnsemble("formaldehyde");
  await page.reload({ waitUntil: "networkidle" });
  await page.mouse.move(800, 600);
  const rec = new Recorder(page, "spectrum", FRAMES);
  await rec.start();
  await rec.focus(page.locator(`[data-testid="jobmanager-row-${seeded.ensemble}"]`), { pad: 90, ease: 0 });
  await rec.hold(500);
  const drawer = await openFromManager(page, rec, seeded.ensemble);
  const panel = drawer.locator('[data-testid="wigner-broadening-panel"]');
  await panel.waitFor({ timeout: 30000 });
  await panel.scrollIntoViewIfNeeded();
  await rec.hold(600);
  await rec.focus(panel, { pad: 16 });
  await rec.hold(1500);
  const fwhm = drawer.locator('[data-testid="wigner-fwhm-slider"]');
  await glide(page, fwhm);
  const w0 = Number(await fwhm.inputValue());
  await slide(page, fwhm, Math.min(Number(await fwhm.getAttribute("max")) || 1, w0 * 3), 18, 90);
  await rec.hold(700);
  await slide(page, fwhm, Math.max(Number(await fwhm.getAttribute("min")) || 0.02, w0 * 0.4), 22, 90);
  await rec.hold(1000);
  const lo = drawer.locator('[data-testid="wigner-window-min"]');
  await glide(page, lo);
  await lo.focus();
  for (let i = 0; i < 14; i++) { await page.keyboard.press("ArrowRight"); await page.waitForTimeout(90); }
  await rec.hold(2200);
  rec.wide();
  await rec.hold(800);
  await rec.stop();
  animate("spectrum", "spectrum.webp");
}

/** 5: vibrations. Two normal modes of a finished frequency job. */
async function vibrations(page) {
  const seeded = seedJobs(`[${pyscfJob("freq", "freq", "", "hf", "formaldehyde", { basis: "6-31g*" })}]`);
  await page.reload({ waitUntil: "networkidle" });
  await page.mouse.move(800, 600);
  const rec = new Recorder(page, "vibrations", FRAMES);
  await rec.start();
  await rec.focus(page.locator(`[data-testid="jobmanager-row-${seeded.ids.freq}"]`), { pad: 90, ease: 0 });
  await rec.hold(500);
  const drawer = await openFromManager(page, rec, seeded.ids.freq);
  const modes = drawer.locator('[data-testid^="vibration-row-"]');
  await modes.first().waitFor({ timeout: 30000 });
  await modes.first().scrollIntoViewIfNeeded();
  await rec.focus(await span(modes.first(), modes.last()), { pad: 30 });
  await rec.hold(700);
  // The C=O stretch and a CH2 wag read best; fall back to the first modes.
  const n = await modes.count();
  for (const i of [Math.min(3, n - 1), Math.min(1, n - 1)]) {
    const m = modes.nth(i);
    await glide(page, m);
    await m.click();
    const viewer = drawer.locator('[data-testid="mode-atom-labels"]').locator("xpath=ancestor::div[.//canvas][1]");
    await viewer.waitFor({ timeout: 30000 });
    await viewer.scrollIntoViewIfNeeded();
    await rec.hold(400);
    await rec.focus(viewer, { pad: 16 });
    await rec.hold(3600);
    await modes.first().scrollIntoViewIfNeeded();
  }
  rec.wide();
  await rec.hold(800);
  await rec.stop();
  animate("vibrations", "vibrations.webp");
}

/** 6: a chart drawn by asking, then restyled by asking. The job is attached
 *  from the Job Manager, so "this job" has one meaning. */
async function plots(page) {
  const seeded = seedJobs(`[${pyscfJob("benzene", "single_point", "gs", "hf", "benzene", { basis: "6-31g*" })}]`);
  const jobId = seeded.ids.benzene;
  await page.reload({ waitUntil: "networkidle" });
  await page.mouse.move(800, 600);
  const rec = new Recorder(page, "plots", FRAMES);
  const tick = page.locator(`[data-testid="jobmanager-select-${jobId}"]`);
  await tick.waitFor({ timeout: 30000 });
  await rec.start();
  await rec.focus(page.locator(`[data-testid="jobmanager-row-${jobId}"]`), { pad: 60, ease: 0 });
  await rec.hold(400);
  await glide(page, tick);
  await tick.check();
  const attach = page.locator('[data-testid="jobmanager-attach-to-prompt"]');
  await glide(page, attach);
  await attach.click();
  await rec.hold(500);
  rec.wide();
  await say(page, rec, "Plot the molecular orbital energy levels of this job");
  const chatPlot = page.locator('img[alt="Plot"][src*="/api/plots/"]');
  await rec.quickly(() => chatPlot.first().waitFor({ timeout: 300000 }), 8);
  await rec.quickly(() => turnDone(page), 8);
  await chatPlot.last().scrollIntoViewIfNeeded();
  await rec.focus(chatPlot.last(), { pad: 20 });
  await rec.hold(3000);
  rec.wide();
  const before = await chatPlot.count();
  await say(page, rec, "Colour the HOMO and LUMO red and make all the text bigger");
  await rec.quickly(() => page.waitForFunction(
    ([sel, n]) => document.querySelectorAll(sel).length > n, ['img[alt="Plot"][src*="/api/plots/"]', before],
    { timeout: 300000 }), 8);
  await rec.quickly(() => turnDone(page), 8);
  await chatPlot.last().scrollIntoViewIfNeeded();
  await rec.focus(chatPlot.last(), { pad: 20 });
  await rec.hold(3500);
  rec.wide();
  await rec.hold(800);
  await rec.stop();
  animate("plots", "plots.webp");
}

/** 7: a failed job, and a diagnosis only when asked for. */
async function troubleshoot(page, { threadId }) {
  seedFailedJob(threadId);
  const card = page.locator("text=Job failed").locator("xpath=ancestor::div[contains(@class,'rounded-bl-sm')][1]");
  // The job watcher writes the failure card into the conversation.
  const end = Date.now() + 90000;
  while (!(await card.count()) && Date.now() < end) {
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(4000);
  }
  await card.first().waitFor({ timeout: 10000 });
  await page.mouse.move(800, 600);
  const rec = new Recorder(page, "troubleshoot", FRAMES);
  await card.first().scrollIntoViewIfNeeded();
  await rec.start();
  await rec.focus(card.first(), { pad: 30, ease: 0 });
  await rec.hold(400);
  await rec.hold(2500);
  const button = card.first().locator('button:has-text("Troubleshoot")');
  await glide(page, button);
  await button.click();
  await rec.hold(800);
  rec.wide();
  await rec.quickly(() => turnDone(page, 600000), 12);
  const reply = lastReply(page);
  await reply.scrollIntoViewIfNeeded();
  await rec.focus(reply, { pad: 30 });
  await rec.hold(4500);
  // A proposed fix comes back as an approval card, which is the better
  // ending: the corrected job still waits for a person.
  const approve = page.locator('[data-testid="approval-approve"]');
  if (await approve.count()) {
    const card = approve.locator("xpath=ancestor::div[contains(@class,'border-accent')][1]");
    await card.scrollIntoViewIfNeeded();
    await rec.focus(card, { pad: 24 });
    await rec.hold(3500);
  }
  rec.wide();
  await rec.hold(800);
  await rec.stop();
  animate("troubleshoot", "troubleshoot.webp");
}

/** 8: finished work filed into a project. Filmed last in a run: the jobs
 *  leave the Job Manager list when they are filed. */
async function projects(page) {
  const seeded = seedJobs(`[${[
    pyscfJob("a", "single_point", "gs", "hf", "water", { basis: "cc-pvdz" }),
    pyscfJob("b", "single_point", "gs", "dft", "water", { basis: "cc-pvdz", functional: "pbe0" }),
    pyscfJob("c", "single_point", "gs", "mp2", "water", { basis: "cc-pvdz" }),
  ].join(", ")}]`);
  const ids = Object.values(seeded.ids);
  await page.reload({ waitUntil: "networkidle" });
  const section = page.locator('[data-testid="section-projects-toggle"]');
  if ((await section.getAttribute("aria-expanded")) === "false") await section.click();
  await page.mouse.move(800, 600);
  const rec = new Recorder(page, "projects", FRAMES);
  await rec.start();
  await rec.focus(await span(...ids.map((id) => page.locator(`[data-testid="jobmanager-row-${id}"]`))), { pad: 60, ease: 0 });
  await rec.hold(400);
  for (const id of ids) {
    const tick = page.locator(`[data-testid="jobmanager-select-${id}"]`);
    await glide(page, tick, 10);
    await tick.check();
    await rec.hold(250);
  }
  const add = page.locator('[data-testid="jobmanager-add-to-project"]');
  await glide(page, add);
  await add.click();
  const name = page.locator('[data-testid="add-to-project-new-name"]');
  await name.waitFor({ timeout: 10000 });
  await typeOut(name, "Water, three levels of theory");
  await rec.hold(300);
  const create = page.locator('[data-testid="add-to-project-create"]');
  await glide(page, create);
  await create.click();
  await rec.hold(1200);
  const panel = page.locator('[data-testid="section-projects-panel"]');
  await rec.focus(panel, { pad: 40 });
  await rec.hold(3000);
  rec.wide();
  await rec.hold(800);
  await rec.stop();
  animate("projects", "projects.webp");
}

/** The active-space recommendation, as a still: the run takes minutes, and
 *  what is worth showing is the finished table, not the wait. An element
 *  screenshot is safe here because the section holds no WebGL canvas. */
async function activeSpace(page) {
  const seeded = seedJobs(`[${pyscfJob("rec", "cas_reco", "", "casscf", "formaldehyde", { n_states: 3 })}]`, 1500);
  if (seeded.status.rec !== "completed") throw new Error(`the recommendation ended ${seeded.status.rec}`);
  await page.reload({ waitUntil: "networkidle" });
  const rec = new Recorder(page, "active-space", FRAMES); // for openFromManager's holds only
  const drawer = await openFromManager(page, rec, seeded.ids.rec);
  const section = drawer.locator("text=Active-space recommendation").first()
    .locator("xpath=ancestor::div[contains(@class,'mb-4')][1]");
  await section.waitFor({ timeout: 30000 });
  // From the recommended space to the states table: the prose and the
  // entropy chart above it make a strip too tall to read in a README row.
  // The labelled line, not the same words opening the summary prose above.
  const top = section.locator("span.font-medium", { hasText: "Recommended active space:" }).first();
  await top.scrollIntoViewIfNeeded();
  await top.evaluate((el) => el.scrollIntoView({ block: "center" }));
  await page.evaluate(() => document.querySelectorAll('[aria-hidden="true"]').forEach((el) => {
    if (el.innerHTML.includes("M3 2l14")) el.style.display = "none";
  }));
  await page.mouse.move(2, 2);
  await page.waitForTimeout(1200);
  const states = section.locator("table").last();
  const a = await top.boundingBox(), b = await section.boundingBox(), c = await states.boundingBox();
  await page.screenshot({
    path: path.join(OUT, "active-space.png"),
    clip: { x: b.x, y: a.y - 8, width: b.width, height: c.y + c.height - a.y + 16 },
  });
  console.log("active-space.png written");
}

// Each scene: the conversation it opens on, and what it does there.
const SCENES = {
  hero: { label: "Formaldehyde UV/Vis, TDDFT", run: (p) => hero(p) },
  "hero-light": { label: "Formaldehyde UV/Vis, TDDFT", theme: "daylight", run: (p) => hero(p, { theme: "daylight" }) },
  asks: { label: "Formaldehyde CASSCF", run: asks },
  molecule: { label: "Caffeine", run: molecule },
  orbitals: { label: "Benzene orbitals", run: orbitals },
  spectrum: { label: "Formaldehyde UV/Vis, nuclear ensemble", run: spectrum },
  vibrations: { label: "Formaldehyde vibrations", run: vibrations },
  plots: { label: "Benzene orbital levels", run: plots },
  troubleshoot: { label: "Water single point", run: troubleshoot },
  "active-space": { label: "Formaldehyde active space", run: activeSpace },
  projects: { label: "Water, three levels of theory", run: projects },
  "probe-hero": { label: "probe hero", run: probeHero },
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
    const scene = SCENES[w];
    const { ctx, page, threadId } = await openApp(browser, { theme: scene.theme, label: scene.label });
    try {
      await scene.run(page, { threadId });
    } catch (e) {
      failed = true;
      console.log(`[FAIL] ${w}: ${e.stack || e}`);
    } finally {
      await ctx.close();
      // Each scene clears up after itself, so the next one's sidebar and
      // job list hold only what that scene made.
      const leftover = await cleanUp(browser, before);
      if (Object.values(leftover).some((v) => v.length)) failed = true;
    }
  }
} finally {
  await browser.close();
}
process.exit(failed ? 1 : 0);
