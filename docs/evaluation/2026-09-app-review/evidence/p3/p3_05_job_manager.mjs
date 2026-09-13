// P3.5 (UI half): the job manager under load, kill/cancel, and R-027 -- a
// job opened from the Job Manager that stops updating in the drawer because
// job_update SSE events only reach the owning thread's stream. The
// leave-and-return / restart / orphan-reconciliation path is already covered
// end to end by tests/e2e/e2e_17_logout_and_return.py, which P1.3 runs; this
// does the parts that live in the UI.
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_05_job_manager.mjs
import fs from "node:fs";
import path from "node:path";
import { start, loginAs, Log, sendMessage, transcript, allCanvases, BASE_URL } from "./_p3.mjs";

const L = new Log("p3_05_job_manager");
const browser = await start();
const { ctx, page, acct } = await loginAs(browser, "qa_review");

async function threadId() {
  const v = await page.evaluate(() => { try { return localStorage.getItem("qc-agent-active-thread"); } catch { return null; } });
  return (v || "").replace(/^"|"$/g, "");
}

// --- R-027: open a RUNNING job from a DIFFERENT conversation ----------------
// Submit a slow-ish job (ORCA CASSCF on water) in conversation 1, then open a
// new conversation 2 and open that job from the Job Manager. The finding says
// its drawer header stays "running" forever while the list row goes terminal.
await L.observe(page, "conv1-new", async () => {
  const b = page.locator('[data-testid="conversation-new"]'); if (await b.count()) await b.click();
  await page.waitForTimeout(600); return {};
}, { inventory: false });

const slow = await L.observe(page, "conv1-submit-slow-job", async () => {
  await sendMessage(page, "Set the molecule to water, then run a CASSCF(4,4)/STO-3G single point on it with ORCA, 1 state.", { timeout: 400000 });
  const card = await page.locator('[data-testid="approval-approve"]').count();
  if (card) await page.locator('[data-testid="approval-approve"]').click();
  await page.waitForTimeout(2500);
  const tid = await threadId();
  const r = await ctx.request.get(`${BASE_URL}/api/threads/${tid}/jobs`);
  const jobs = r.ok() ? await r.json() : [];
  const list = (Array.isArray(jobs) ? jobs : jobs.jobs || []);
  return { thread: tid, jobs: list.map((j) => ({ id: j.id || j.job_id, status: j.status })) };
});
const slowJob = (slow.result && slow.result.jobs && slow.result.jobs[0] && slow.result.jobs[0].id) || null;
L.note(`slow job id: ${slowJob}`);

await L.observe(page, "conv2-open-and-view-foreign-running-job", async () => {
  if (!slowJob) return { skipped: "no slow job" };
  const b = page.locator('[data-testid="conversation-new"]'); if (await b.count()) await b.click();
  await page.waitForTimeout(800);
  // Open the Job Manager and click the running job (which belongs to conv 1).
  const jm = page.locator('[data-testid="jobmanager-filters"], [title="Jobs"], [data-testid="user-menu-open"]').first();
  // Find the job row directly.
  const row = page.locator(`text=/${slowJob.slice(0, 8)}/`).first();
  const found = await row.count();
  if (found) { await row.click().catch(() => {}); await page.waitForTimeout(1500); }
  // Read the drawer header status, and separately the list row / API status.
  const headerRunning = await page.locator('[data-testid="chat-header-running"]').count();
  const drawerText = await page.evaluate(() => (document.body.innerText || "").slice(0, 1200));
  const api = await ctx.request.get(`${BASE_URL}/api/jobs/${slowJob}`);
  const apiStatus = api.ok() ? (await api.json()).status : `http ${api.status()}`;
  return { row_found: found > 0, drawer_header_running_marker: headerRunning, api_status: apiStatus, drawer_excerpt: drawerText };
});

// Poll the drawer while the job finishes: does the DRAWER ever show terminal,
// or does only the API/list flip? This is the R-027 measurement.
await L.observe(page, "conv2-watch-drawer-vs-api", async () => {
  if (!slowJob) return { skipped: "no slow job" };
  const samples = [];
  const t = Date.now();
  while (Date.now() - t < 300000) {
    const api = await ctx.request.get(`${BASE_URL}/api/jobs/${slowJob}`);
    const apiStatus = api.ok() ? (await api.json()).status : `http ${api.status()}`;
    const drawerSaysCompleted = await page.evaluate(() => /completed|energy|finished/i.test(document.body.innerText.slice(-2000)));
    const drawerSaysRunning = await page.evaluate(() => /running/i.test(document.body.innerText.slice(-2000)));
    samples.push({ ms: Date.now() - t, api: apiStatus, drawer_completed: drawerSaysCompleted, drawer_running: drawerSaysRunning });
    if (apiStatus === "completed" || apiStatus === "failed") {
      // Give the drawer 30 s of grace to catch up via SSE, then sample twice more.
      await page.waitForTimeout(15000);
      const d1 = await page.evaluate(() => /completed|energy|finished/i.test(document.body.innerText.slice(-2000)));
      await page.waitForTimeout(15000);
      const d2 = await page.evaluate(() => /completed|energy|finished/i.test(document.body.innerText.slice(-2000)));
      samples.push({ note: "15s and 30s after API terminal", drawer_completed_after_grace: [d1, d2] });
      break;
    }
    await page.waitForTimeout(5000);
  }
  return { samples };
}, { inventory: false });

// --- kill / cancel buttons ---------------------------------------------------
await L.observe(page, "cancel-button", async () => {
  // Submit another slow job and cancel it from the UI.
  const b = page.locator('[data-testid="conversation-new"]'); if (await b.count()) await b.click();
  await page.waitForTimeout(600);
  await sendMessage(page, "Run a CASSCF(4,4)/STO-3G single point on water with ORCA, 1 state.", { timeout: 400000 });
  if (await page.locator('[data-testid="approval-approve"]').count()) await page.locator('[data-testid="approval-approve"]').click();
  await page.waitForTimeout(4000);
  const kill = page.locator('[data-testid="jobmanager-kill"], button[title*="Stop" i], button[title*="Cancel" i], [aria-label*="cancel" i]').first();
  const found = await kill.count();
  let after = null;
  if (found) { await kill.click().catch(() => {}); await page.waitForTimeout(3000);
    const tid = await threadId();
    const r = await ctx.request.get(`${BASE_URL}/api/threads/${tid}/jobs`);
    const jobs = r.ok() ? await r.json() : [];
    after = (Array.isArray(jobs) ? jobs : jobs.jobs || []).map((j) => ({ id: (j.id||j.job_id||"").slice(0,8), status: j.status }));
  }
  return { cancel_control_found: found > 0, jobs_after: after };
});

// --- job manager search, filters, sort ---------------------------------------
await L.observe(page, "job-manager-controls", async () => {
  const testids = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-testid^="jobmanager"]')).map((e) => e.getAttribute("data-testid")));
  const search = page.locator('input[placeholder*="earch" i]').first();
  let searchWorks = null;
  if (await search.count()) { await search.fill("water"); await page.waitForTimeout(800);
    searchWorks = await page.evaluate(() => document.querySelectorAll('[data-testid="jobmanager-search-empty"]').length === 0); }
  return { jobmanager_testids: [...new Set(testids)], search_present: await search.count() > 0, search_returned_rows: searchWorks };
});

fs.writeFileSync(path.join(L.shotDir, "requests.json"), JSON.stringify(page.__requests, null, 1));
await ctx.close(); await browser.close();
console.log(`\nevidence: ${L.file}\nscreenshots: ${L.shotDir}/`);
