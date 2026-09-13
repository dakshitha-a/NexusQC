// P3.6, P3.7, P3.8 combined: follow-up questions and plots (6), projects and
// sharing (7), and the admin console (8). Kept in one driver because they
// share the same two logged-in contexts (qa_review, qa_review_2) and an admin
// context, and running them together avoids three separate stack warm-ups.
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   QC_AGENT_TEST_ADMIN_USER=qatest_admin \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_06_08_followups_projects_admin.mjs
//
// No danger-zone purge and no real in-app update are exercised, per the
// protocol. Admin reads and non-destructive admin writes only.
import fs from "node:fs";
import path from "node:path";
import { start, loginAs, Log, sendMessage, transcript, BASE_URL, newContext, adminApiLogin } from "./_p3.mjs";

const L = new Log("p3_06_08_followups_projects_admin");
const browser = await start();

// ===== P3.6: follow-ups and plots =========================================
{
  const { ctx, page } = await loginAs(browser, "qa_review");
  async function turn(name, text) {
    return L.observe(page, name, async () => {
      const t = Date.now();
      await sendMessage(page, text, { timeout: 300000 });
      return { turn_ms: Date.now() - t, reply_tail: (await transcript(page)).slice(-2000) };
    });
  }
  await L.observe(page, "p6-new-conv", async () => { const b = page.locator('[data-testid="conversation-new"]'); if (await b.count()) await b.click(); await page.waitForTimeout(600); return {}; }, { inventory: false });
  // Seed a completed job to ask about.
  await turn("p6-seed-job", "Run an HF/STO-3G single point on water with PySCF.");
  await L.observe(page, "p6-approve-seed", async () => { if (await page.locator('[data-testid="approval-approve"]').count()) await page.locator('[data-testid="approval-approve"]').click(); await page.waitForTimeout(8000); return { reply_tail: (await transcript(page)).slice(-1200) }; }, { inventory: false });
  await turn("p6-followup-energy", "What was the total energy of that calculation, in eV?");
  await turn("p6-followup-geometry", "What is the O-H bond length in that water molecule?");
  await turn("p6-unit-conversion", "Convert -75.0 hartree to kcal/mol.");
  await turn("p6-capability-question", "Can BAGEL compute a CASPT2 gradient in this app?");
  // A plot.
  await turn("p6-plot-request", "Plot the potential energy surface of water as the O-H bond stretches from 0.8 to 1.4 angstrom, HF/STO-3G on PySCF.");
  await L.observe(page, "p6-approve-scan", async () => { if (await page.locator('[data-testid="approval-approve"]').count()) await page.locator('[data-testid="approval-approve"]').click(); await page.waitForTimeout(3000); return {}; }, { inventory: false });
  // KB: add a text source, then confirm it is scoped to this user.
  await L.observe(page, "p6-kb-add-text", async () => {
    const tid = (await page.evaluate(() => { try { return localStorage.getItem("qc-agent-active-thread"); } catch { return null; } }) || "").replace(/^"|"$/g, "");
    const r = await ctx.request.post(`${BASE_URL}/api/kb/sources/text`, { data: { text: "Review test note: the answer is 42.", doc_type: "paper", filename: "review-note.txt" }, headers: { "content-type": "application/json" } });
    return { status: r.status(), body: r.ok() ? await r.json() : await r.text() };
  }, { inventory: false });
  await L.observe(page, "p6-kb-list", async () => {
    const r = await ctx.request.get(`${BASE_URL}/api/kb/sources`);
    return { sources: r.ok() ? await r.json() : `http ${r.status()}` };
  }, { inventory: false });
  fs.writeFileSync(path.join(L.shotDir, "p6-requests.json"), JSON.stringify(page.__requests, null, 1));
  await ctx.close();
}

// ===== P3.7: projects and sharing =========================================
{
  const a = await loginAs(browser, "qa_review");
  const b = await loginAs(browser, "qa_review_2");
  // Create a project and add a job via the API (the UI popover is also
  // screenshotted, but the API is the reliable way to set state).
  await L.observe(a.page, "p7-create-project", async () => {
    const r = await a.ctx.request.post(`${BASE_URL}/api/projects`, { data: { name: "Review project" }, headers: { "content-type": "application/json" } });
    return { status: r.status(), project: r.ok() ? await r.json() : await r.text() };
  }, { inventory: false });
  await L.observe(a.page, "p7-projects-panel", async () => {
    // Open the projects flyout in the UI and screenshot it.
    const opener = a.page.locator('[title="Projects"], [data-testid="user-menu-open"]').first();
    await opener.click().catch(() => {});
    await a.page.waitForTimeout(1000);
    return { text: (await a.page.evaluate(() => document.body.innerText)).slice(-1500) };
  });
  // Share: qa_review shares a thread with qa_review_2.
  await L.observe(a.page, "p7-share-roundtrip", async () => {
    const r = await a.ctx.request.get(`${BASE_URL}/api/threads`);
    const th = (await r.json()); const tid = ((Array.isArray(th) ? th : th.threads || [])[0] || {});
    const target = (tid.id || tid.thread_id);
    if (!target) return { skipped: "no thread to share" };
    // Find qa_review_2's user id via search.
    const s = await a.ctx.request.get(`${BASE_URL}/api/users/search?q=qa_review_2`);
    const users = s.ok() ? await s.json() : [];
    const recipient = (Array.isArray(users) ? users : users.users || [])[0];
    const share = await a.ctx.request.post(`${BASE_URL}/api/shares`, { data: { thread_id: target, recipient_id: recipient && (recipient.id) }, headers: { "content-type": "application/json" } });
    return { share_status: share.status(), recipient_found: !!recipient, body: share.ok() ? await share.json() : await share.text() };
  }, { inventory: false });
  await L.observe(b.page, "p7-recipient-inbox", async () => {
    const r = await b.ctx.request.get(`${BASE_URL}/api/shares/inbox`);
    return { inbox: r.ok() ? await r.json() : `http ${r.status()}` };
  }, { inventory: false });
  await a.ctx.close(); await b.ctx.close();
}

// ===== P3.8: the admin console ============================================
{
  const ctx = await newContext(browser);
  const ok = await adminApiLogin(ctx).then(() => true).catch(() => false);
  const page = await ctx.newPage();
  L.note(`admin api login: ${ok}`);
  // Read every admin section through the UI, screenshotting each, and record
  // the read-only API responses.
  await L.observe(page, "p8-admin-panel", async () => {
    await page.goto(`${BASE_URL}/`);
    await page.waitForTimeout(1500);
    // Admin sign-in through the real screen would need the password; instead
    // read the admin API with the context cookie set by adminApiLogin.
    const out = {};
    for (const [k, p] of [["overview", "/api/admin/storage"], ["users", "/api/admin/users"], ["invites", "/api/admin/invites"], ["audit", "/api/admin/audit-log"], ["config", "/api/admin/config"], ["deployment", "/api/admin/deployment"], ["activity", "/api/admin/activity"], ["bug-reports", "/api/admin/bug-reports"]]) {
      const r = await ctx.request.get(`${BASE_URL}${p}`);
      out[k] = { status: r.status(), sample: r.ok() ? JSON.stringify(await r.json()).slice(0, 300) : null };
    }
    return out;
  }, { inventory: false });
  // A non-destructive admin write: mint then revoke an invite, and confirm
  // both are audited.
  await L.observe(page, "p8-invite-lifecycle-audited", async () => {
    const before = await ctx.request.get(`${BASE_URL}/api/admin/audit-log`);
    const beforeN = before.ok() ? (await before.json()).length || (await before.json()).entries?.length : null;
    const mint = await ctx.request.post(`${BASE_URL}/api/admin/invites`, { data: { role: "user", ttl_hours: 24 }, headers: { "content-type": "application/json" } });
    const token = mint.ok() ? (await mint.json()).token : null;
    let revoke = null;
    if (token) revoke = (await ctx.request.post(`${BASE_URL}/api/admin/invites/${token}/revoke`, { data: {}, headers: { "content-type": "application/json" } })).status();
    const after = await ctx.request.get(`${BASE_URL}/api/admin/audit-log`);
    const afterN = after.ok() ? (await after.json()).length || (await after.json()).entries?.length : null;
    return { mint_status: mint.status(), revoke_status: revoke, audit_before: beforeN, audit_after: afterN };
  }, { inventory: false });
  await ctx.close();
}

await browser.close();
console.log(`\nevidence: ${L.file}`);
