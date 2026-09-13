// P3.9: two users at once, isolation and quotas. The single most important
// step of the walkthrough, because R-001, R-003 and R-009 are all cross-user
// reads and this is where they are proven or disproven against the running
// app rather than the code. qa_review owns things; qa_review_2 tries to reach
// them; every attempt should be 403 or 404, never content.
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_09_isolation.mjs
//
// This drives the API directly through an authenticated browser context (the
// cookie the UI uses), which is the right level for an isolation sweep: it is
// exactly what a malicious logged-in user can do from the console.
import fs from "node:fs";
import path from "node:path";
import { start, loginAs, Log, BASE_URL, accounts } from "./_p3.mjs";

const L = new Log("p3_09_isolation");
const browser = await start();

// Log both users in so we have both authenticated contexts.
const a = await loginAs(browser, "qa_review");
const b = await loginAs(browser, "qa_review_2");
const acctA = accounts().qa_review, acctB = accounts().qa_review_2;

// A tiny helper: GET a path in a given context and classify the result.
async function get(ctx, p) {
  const r = await ctx.request.get(`${BASE_URL}${p}`);
  const status = r.status();
  let bytes = 0, kind = "?";
  try { const buf = await r.body(); bytes = buf.length; } catch {}
  const ct = r.headers()["content-type"] || "";
  return { status, bytes, ct };
}
async function post(ctx, p, data) {
  const r = await ctx.request.post(`${BASE_URL}${p}`, { data, headers: { "content-type": "application/json" } });
  return { status: r.status() };
}

// --- Seed a GENUINELY-OWNED job for qa_review -------------------------------
// GET /api/jobs returns unowned jobs too (visible to everyone by design), so
// its output cannot be treated as "owned by A". To test real isolation we
// need a job with a recorded ownership row. Submit one through the API as
// qa_review (JobManager.submit records ownership for an authenticated caller),
// wait for it to complete, and test qa_review_2's access to THAT.
const A_OWNED = await L.observe(a.page, "seed-owned-job-for-A", async () => {
  // Drive a real turn so the job is created and owned the way the app does it.
  const r = await a.ctx.request.get(`${BASE_URL}/api/threads`);
  const th = await r.json();
  let tid = ((Array.isArray(th) ? th : th.threads || [])[0] || {});
  tid = tid.id || tid.thread_id;
  if (!tid) {
    const c = await a.ctx.request.post(`${BASE_URL}/api/threads`, { data: {}, headers: { "content-type": "application/json" } });
    tid = (await c.json()).thread_id || (await c.json()).id;
  }
  // Submit a trivial owned job directly via the jobs API is not exposed; use
  // the agent turn path with a fully-specified request, then read the job id.
  await a.ctx.request.post(`${BASE_URL}/api/threads/${tid}/messages`, {
    data: { text: "Run an HF/STO-3G single point on water with PySCF." }, headers: { "content-type": "application/json" } });
  // Poll the thread's jobs for a new id (the agent will draft; we approve via API).
  let jobId = null, pending = null;
  for (let i = 0; i < 40 && !jobId; i++) {
    await a.page.waitForTimeout(3000);
    const st = await (await a.ctx.request.get(`${BASE_URL}/api/threads/${tid}/state`)).json();
    pending = st.pending_approval || st.state?.pending_approval;
    if (pending) {
      await a.ctx.request.post(`${BASE_URL}/api/threads/${tid}/approvals/job`, { data: { approved: true }, headers: { "content-type": "application/json" } });
    }
    const jr = await a.ctx.request.get(`${BASE_URL}/api/threads/${tid}/jobs`);
    const jobs = jr.ok() ? await jr.json() : [];
    const list = Array.isArray(jobs) ? jobs : jobs.jobs || [];
    if (list.length) jobId = (list[0].id || list[0].job_id);
  }
  return { thread: tid, jobId };
}, { inventory: false });
const A_OWNED_JOB = A_OWNED.result && A_OWNED.result.jobId;
L.note(`qa_review's genuinely-owned seeded job: ${A_OWNED_JOB}`);

// --- Enumerate what A can SEE (jobs list includes unowned; label honestly) --
const owned = await L.observe(a.page, "enumerate-visible-to-A", async () => {
  const out = {};
  for (const [k, p] of [["jobs", "/api/jobs"], ["threads", "/api/threads"], ["plots", "/api/plots"], ["projects", "/api/projects"]]) {
    const r = await a.ctx.request.get(`${BASE_URL}${p}`);
    const d = r.ok() ? await r.json() : [];
    const items = Array.isArray(d) ? d : (d[k] || d.items || []);
    out[k] = items.map((it) => it.id || it.job_id || it.thread_id).filter(Boolean);
  }
  // The one job we KNOW A owns (has an ownership row) is the seeded one; the
  // rest of the jobs list may be unowned leftovers visible to everyone.
  out.a_owned_job = A_OWNED_JOB;
  out.jobs_note = "GET /api/jobs includes unowned jobs (visible to all by design); only a_owned_job is proven A-owned";
  return out;
}, { inventory: false });

// Also grab the master with unowned children we found in P0.5, so the sweep
// covers a child job specifically.
const KNOWN_UNOWNED_CHILD = "0d87ea39ec68";
const KNOWN_MASTER = "186fe458ec9e";

// --- The cross-user sweep: qa_review_2 tries to reach qa_review's things ----
await L.observe(b.page, "cross-user-read-sweep", async () => {
  const res = owned.result || {};
  const targets = [];
  // The genuinely-owned job first, clearly labelled: this is the real isolation test.
  if (res.a_owned_job) {
    const j = res.a_owned_job;
    targets.push([`GET /api/jobs/${j} (A-OWNED)`, () => get(b.ctx, `/api/jobs/${j}`)]);
    targets.push([`GET /api/jobs/${j}/download (A-OWNED)`, () => get(b.ctx, `/api/jobs/${j}/download`)]);
    targets.push([`GET /api/jobs/${j}/log (A-OWNED)`, () => get(b.ctx, `/api/jobs/${j}/log`)]);
  }
  // The rest of the visible list, labelled as possibly-unowned so the report
  // does not mistake settled unowned-visibility for a leak.
  for (const j of (res.jobs || []).filter((x) => x !== res.a_owned_job)) {
    targets.push([`GET /api/jobs/${j} (visible, maybe unowned)`, () => get(b.ctx, `/api/jobs/${j}`)]);
  }
  for (const th of (res.threads || [])) {
    targets.push([`GET /api/threads/${th}/state`, () => get(b.ctx, `/api/threads/${th}/state`)]);
    targets.push([`GET /api/threads/${th}/jobs`, () => get(b.ctx, `/api/threads/${th}/jobs`)]);
  }
  for (const pl of (res.plots || [])) targets.push([`GET /api/plots/${pl}`, () => get(b.ctx, `/api/plots/${pl}`)]);
  for (const pr of (res.projects || [])) {
    targets.push([`GET /api/projects/${pr}`, () => get(b.ctx, `/api/projects/${pr}`)]);
    targets.push([`GET /api/projects/${pr}/download`, () => get(b.ctx, `/api/projects/${pr}/download`)]);
  }
  // The child-job finding, explicitly:
  targets.push([`GET /api/jobs/${KNOWN_MASTER} (owned master)`, () => get(b.ctx, `/api/jobs/${KNOWN_MASTER}`)]);
  targets.push([`GET /api/jobs/${KNOWN_UNOWNED_CHILD} (its child)`, () => get(b.ctx, `/api/jobs/${KNOWN_UNOWNED_CHILD}`)]);
  targets.push([`GET /api/jobs/${KNOWN_UNOWNED_CHILD}/download`, () => get(b.ctx, `/api/jobs/${KNOWN_UNOWNED_CHILD}/download`)]);

  const rows = [];
  for (const [label, fn] of targets) {
    const r = await fn();
    const leaked = r.status === 200 && r.bytes > 50;
    rows.push({ label, ...r, VERDICT: leaked ? "LEAK" : "denied" });
  }
  return { leaks: rows.filter((x) => x.VERDICT === "LEAK").length, rows };
}, { inventory: false });

// --- R-003: post another user's job_ids into your OWN thread ---------------
await L.observe(b.page, "cross-user-job-into-own-thread", async () => {
  // qa_review_2's own thread:
  const mine = (owned.result && owned.result.threads) || [];
  const r = await b.ctx.request.get(`${BASE_URL}/api/threads`);
  const myThreads = r.ok() ? await r.json() : [];
  const myThread = (Array.isArray(myThreads) ? myThreads : myThreads.threads || [])[0];
  if (!myThread) return { skipped: "qa_review_2 has no thread yet" };
  const tid = myThread.id || myThread.thread_id;
  const victimJob = (owned.result.jobs || [])[0] || KNOWN_UNOWNED_CHILD;
  const resp = await post(b.ctx, `/api/threads/${tid}/messages`, { text: `Summarise the results of this job.`, job_ids: [victimJob] });
  // Then read the thread state back and see whether the victim job's content
  // reached the conversation.
  await b.page.waitForTimeout(4000);
  const st = await b.ctx.request.get(`${BASE_URL}/api/threads/${tid}/state`);
  const body = st.ok() ? JSON.stringify(await st.json()) : "";
  return { post_status: resp.status, victim_job: victimJob, victim_id_in_thread_state: body.includes(victimJob), thread_state_chars: body.length };
}, { inventory: false });

// --- R-003 again: troubleshoot another user's job --------------------------
await L.observe(b.page, "cross-user-troubleshoot", async () => {
  const r = await b.ctx.request.get(`${BASE_URL}/api/threads`);
  const myThreads = r.ok() ? await r.json() : [];
  const myThread = (Array.isArray(myThreads) ? myThreads : myThreads.threads || [])[0];
  if (!myThread) return { skipped: "no thread" };
  const tid = myThread.id || myThread.thread_id;
  const victimJob = (owned.result.jobs || [])[0] || KNOWN_UNOWNED_CHILD;
  const resp = await post(b.ctx, `/api/threads/${tid}/troubleshoot/${victimJob}`, {});
  return { status: resp.status, VERDICT: resp.status === 202 ? "ACCEPTED (should be denied)" : "denied/other" };
}, { inventory: false });

// --- write attempts on a cross-user / unowned job --------------------------
await L.observe(b.page, "cross-user-write-attempts", async () => {
  const jid = KNOWN_UNOWNED_CHILD;
  const rename = await b.ctx.request.patch(`${BASE_URL}/api/jobs/${jid}`, { data: { name: "hijacked by qa_review_2" }, headers: { "content-type": "application/json" } });
  // Do NOT actually delete or cancel; just record what the server would allow
  // by checking the status code of a rename, which is the least destructive
  // write. A 200 here is the write half of R-001.
  return { patch_rename_status: rename.status(), VERDICT: rename.status() === 200 ? "RENAME ALLOWED (cross-user write)" : "denied" };
}, { inventory: false });

L.note("write sweep did rename only, and did not cancel or delete anything");
fs.writeFileSync(path.join(L.shotDir, "owned.json"), JSON.stringify(owned.result || {}, null, 1));
await a.ctx.close(); await b.ctx.close(); await browser.close();
console.log(`\nevidence: ${L.file}`);
