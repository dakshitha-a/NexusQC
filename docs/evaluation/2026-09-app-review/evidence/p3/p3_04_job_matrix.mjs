// P3.4: the job matrix through the agent, and every viewer. This is the
// expensive one. It drives the registry cells that the probe suite (P1.3)
// does not already cover, and for each completed job it opens the drawer,
// screenshots every viewer, reads whether each canvas actually drew, checks
// that a download link exists and is named per the safename_descriptor.ext
// rule, and reads the number back four ways where it cheaply can.
//
// Runs everything on qa_review with tiny systems. The heavy engine cells
// (BAGEL, CASSCF) are left to P1.3's e2e_08 tier 3; this covers the UI-side
// surfaces and the tasks e2e_08 skips: wigner_spectra, batch, cas_reco,
// geometry_set, interp_pes/ee.
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_04_job_matrix.mjs
import fs from "node:fs";
import path from "node:path";
import { start, loginAs, Log, sendMessage, transcript, allCanvases, BASE_URL } from "./_p3.mjs";

const L = new Log("p3_04_job_matrix");
const browser = await start();
const { ctx, page } = await loginAs(browser, "qa_review");

async function threadId() {
  const v = await page.evaluate(() => { try { return localStorage.getItem("qc-agent-active-thread"); } catch { return null; } });
  return (v || "").replace(/^"|"$/g, "");
}
async function jobsOnThread() {
  const tid = await threadId(); if (!tid) return [];
  const r = await ctx.request.get(`${BASE_URL}/api/threads/${tid}/jobs`);
  if (!r.ok()) return [];
  const d = await r.json();
  return (Array.isArray(d) ? d : d.jobs || []).map((j) => ({ id: j.id || j.job_id, status: j.status, task: j.task, name: j.name }));
}

/** Run one request to completion (approve if a card appears), then inspect
 *  the drawer and its viewers. */
async function matrixCell(cid, prompt, { approveTimeout = 600000 } = {}) {
  await L.observe(page, `${cid}-new-conv`, async () => {
    const b = page.locator('[data-testid="conversation-new"]'); if (await b.count()) await b.click();
    await page.waitForTimeout(600); return {};
  }, { inventory: false });

  const submit = await L.observe(page, `${cid}-request`, async () => {
    const t = Date.now();
    await sendMessage(page, prompt, { timeout: 400000 });
    await page.waitForTimeout(500);
    const hasCard = await page.locator('[data-testid="approval-approve"]').count();
    return { turn_ms: Date.now() - t, card: hasCard > 0, reply_tail: (await transcript(page)).slice(-1200) };
  });
  if (!submit.result || !submit.result.card) {
    L.note(`${cid}: no approval card, cannot proceed to a job`, { cid });
    return;
  }
  await L.observe(page, `${cid}-approve`, async () => {
    await page.locator('[data-testid="approval-approve"]').click();
    await page.waitForTimeout(2000);
    return { jobs: await jobsOnThread() };
  }, { inventory: false });

  // Wait for the job to reach a terminal state via the API, not the UI.
  const done = await L.observe(page, `${cid}-await-terminal`, async () => {
    const t = Date.now();
    let jobs = [];
    while (Date.now() - t < approveTimeout) {
      jobs = await jobsOnThread();
      if (jobs.length && jobs.every((j) => ["completed", "failed", "cancelled"].includes(j.status))) break;
      await page.waitForTimeout(4000);
    }
    return { wait_ms: Date.now() - t, jobs };
  }, { inventory: false });

  // Open the drawer for the (first) job and inspect every viewer.
  await L.observe(page, `${cid}-drawer`, async () => {
    // A job row in the manager or the chat opens the drawer; click the first
    // job name we can find.
    const jobs = (done.result && done.result.jobs) || [];
    const jid = jobs[0] && jobs[0].id;
    if (!jid) return { skipped: "no job" };
    // Open via the job manager panel if present.
    const opener = page.locator(`[data-job-id="${jid}"], text=/${jid.slice(0, 8)}/`).first();
    if (await opener.count()) { await opener.click().catch(() => {}); await page.waitForTimeout(1500); }
    const canvases = await allCanvases(page);
    // Every download control in the drawer, and whether its name follows the rule.
    const downloads = await page.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll('a[download], [data-testid^="drawer-download"], [data-testid="drawer-download-geometry"]')) {
        out.push({ testid: el.getAttribute("data-testid"), download: el.getAttribute("download"), text: (el.textContent || "").trim().slice(0, 40) });
      }
      return out;
    });
    return { job: jid, status: jobs[0].status, canvases, downloads, drawer_text: (await page.evaluate(() => (document.body.innerText || "").slice(0, 2500))) };
  });
}

// --- cells the probe suite does not cover -----------------------------------
await matrixCell("wigner", "Set the molecule to water, then run a Wigner nuclear-ensemble UV-vis spectrum: first a frequency job, then sample 20 geometries and take TDDFT excited states, B3LYP/STO-3G on PySCF, 3 states.");
await matrixCell("cas_reco", "For water, recommend a CASSCF active space. Use PySCF.");
await matrixCell("batch", "Run single-point HF/STO-3G energies on water, methane and ammonia together as a batch on PySCF.");
await matrixCell("geometry_set", "I want to look at a few geometries of water side by side."); // may elicit an attach; recorded either way
await matrixCell("interp_pes", "Interpolate a path between two geometries of water and compute the energy along it with HF/STO-3G on PySCF.");
await matrixCell("opt_pyscf", "Optimise the geometry of water with HF/STO-3G on PySCF.");
await matrixCell("freq_pyscf", "Compute the vibrational frequencies of water with HF/STO-3G on PySCF.");
await matrixCell("ee_pyscf", "Compute the first 3 excited states of water with TDDFT, B3LYP/STO-3G on PySCF, and their oscillator strengths.");

fs.writeFileSync(path.join(L.shotDir, "requests.json"), JSON.stringify(page.__requests, null, 1));
await ctx.close(); await browser.close();
console.log(`\nevidence: ${L.file}\nscreenshots: ${L.shotDir}/`);
