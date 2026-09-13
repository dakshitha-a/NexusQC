// P3.3: drafting, elicitation and the approval gate. An underspecified
// request and what it asks; a complete request and whether it over-asks;
// misspellings and the keyword suggestions; an unsupported pairing; the
// approval card itself, hand-edited, invalidly edited, rejected, and left
// stale by a new request; the instant confirmation on approve; and whether
// the tool trace shows submit_draft was actually called.
//
// Every job here is tiny (water / HF / STO-3G on PySCF) and owned by
// qa_review, so P6.2 removes it.
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_03_drafting.mjs
import fs from "node:fs";
import path from "node:path";
import { start, loginAs, Log, sendMessage, transcript, BASE_URL } from "./_p3.mjs";

const L = new Log("p3_03_drafting");
const browser = await start();
const { ctx, page, acct } = await loginAs(browser, "qa_review");

// The tool trace is the primary observation channel (tests/e2e/README.md):
// read it back from the thread state after each turn.
async function threadId() {
  return page.evaluate(() => { try { return localStorage.getItem("qc-agent-active-thread"); } catch { return null; } });
}
async function toolTrace() {
  const tid = (await threadId() || "").replace(/^"|"$/g, "");
  if (!tid) return { error: "no active thread id in localStorage" };
  const r = await ctx.request.get(`${BASE_URL}/api/threads/${tid}/state`);
  if (!r.ok()) return { error: `state ${r.status()}` };
  const st = await r.json();
  const msgs = st.messages || st.state?.messages || [];
  const calls = [];
  for (const m of msgs) for (const tc of (m.tool_calls || [])) calls.push({ name: tc.name, args: tc.args });
  return { n_messages: msgs.length, tool_calls: calls.slice(-12), pending_approval: !!(st.pending_approval || st.state?.pending_approval) };
}
async function card() {
  const has = await page.locator('[data-testid="approval-approve"]').count();
  if (!has) return { present: false };
  const params = await page.locator('[data-testid="approval-params"]').innerText().catch(() => "");
  const unstated = await page.locator('[data-testid="approval-unstated-params"]').innerText().catch(() => "");
  const defaults = await page.locator('[data-testid="approval-applied-defaults"]').innerText().catch(() => "");
  const warn = await page.locator('[data-testid="approval-input-warnings"]').innerText().catch(() => "");
  const problems = await page.locator('[data-testid="approval-definite-problems"]').innerText().catch(() => "");
  return { present: true, params: params.slice(0, 1500), unstated: unstated.slice(0, 600), applied_defaults: defaults.slice(0, 600), warnings: warn.slice(0, 600), problems: problems.slice(0, 600) };
}
async function turn(name, text, { timeout = 400000 } = {}) {
  return L.observe(page, name, async () => {
    const t = Date.now();
    await sendMessage(page, text, { timeout });
    await page.waitForTimeout(500);
    return { turn_ms: Date.now() - t, reply_tail: (await transcript(page)).slice(-2500), card: await card(), trace: await toolTrace(), console: page.__console.splice(0) };
  });
}

await L.observe(page, "new-conversation", async () => {
  const b = page.locator('[data-testid="conversation-new"]'); if (await b.count()) await b.click();
  await page.waitForTimeout(800); return {};
});
await turn("load-water", "Load water.");

// --- underspecified: what does it ask, and does it ask one thing at a time? --
await turn("underspecified-1", "Run a calculation on it.");
await turn("underspecified-2", "A single point energy.");
await turn("underspecified-3", "Hartree-Fock.");
await turn("underspecified-4", "STO-3G, on PySCF.");
// At this point a card should exist. Reject it so the next scenario starts clean.
await L.observe(page, "reject-first-card", async () => {
  const r = page.locator('[data-testid="approval-reject"]');
  const present = await r.count();
  if (present) { await r.click(); await page.waitForTimeout(1500); }
  return { had_card: present > 0, after: await card(), reply_tail: (await transcript(page)).slice(-800) };
});

// --- complete request: no questions expected ------------------------------------
await turn("complete-request", "Run a single point HF/STO-3G energy on water using PySCF.");
await L.observe(page, "reject-second-card", async () => {
  const r = page.locator('[data-testid="approval-reject"]'); if (await r.count()) { await r.click(); await page.waitForTimeout(1500); }
  return { after: await card() };
});

// --- misspellings and keyword suggestions -----------------------------------------
await turn("misspelled-basis", "Single point energy on water, HF, basis sto3g, PySCF.");
await L.observe(page, "reject-misspelled", async () => {
  const r = page.locator('[data-testid="approval-reject"]'); if (await r.count()) { await r.click(); await page.waitForTimeout(1500); }
  return { after: await card() };
});
await turn("misspelled-functional", "DFT single point on water with the b3lp functional and def2-svp, on ORCA.");
await L.observe(page, "reject-misspelled-2", async () => {
  const r = page.locator('[data-testid="approval-reject"]'); if (await r.count()) { await r.click(); await page.waitForTimeout(1500); }
  return { after: await card() };
});
// R-004 in the register: does asking for L-PDFT get you L-PDFT?
await turn("lpdft-request", "Run an L-PDFT single point on water with a (4,4) active space, tPBE, STO-3G, two states, on PySCF.");
await L.observe(page, "reject-lpdft", async () => {
  const r = page.locator('[data-testid="approval-reject"]'); if (await r.count()) { await r.click(); await page.waitForTimeout(1500); }
  return { after: await card() };
});

// --- an unsupported pairing: refused, and how ------------------------------------
await turn("unsupported-pairing", "Run a CASPT2 geometry optimisation of water on PySCF.");
await L.observe(page, "reject-if-any-3", async () => {
  const r = page.locator('[data-testid="approval-reject"]'); if (await r.count()) { await r.click(); await page.waitForTimeout(1500); }
  return { after: await card() };
});
// R-028: a cell the registry offers and the runner refuses.
await turn("registry-offers-runner-refuses", "Optimise the geometry of water with MP2 and STO-3G on PySCF.");
const mp2card = await card();
L.note(`MP2 opt on PySCF: card present = ${mp2card.present}`);
if (mp2card.present) {
  await L.observe(page, "approve-mp2-opt-to-see-what-happens", async () => {
    const t = Date.now();
    await page.locator('[data-testid="approval-approve"]').click();
    await page.waitForTimeout(3000);
    return { ms_to_first_change: Date.now() - t, reply_tail: (await transcript(page)).slice(-1500), trace: await toolTrace() };
  });
  await L.observe(page, "mp2-opt-outcome-after-60s", async () => {
    await page.waitForTimeout(60000);
    return { reply_tail: (await transcript(page)).slice(-2000) };
  });
}

// --- the approval card in earnest -----------------------------------------------------
await turn("card-for-editing", "Single point HF/STO-3G on water with PySCF.");
await L.observe(page, "card-readability", async () => ({ card: await card() }), { inventory: true });

// Hand-edit: change the basis in the input text. Then an invalid edit.
await L.observe(page, "card-hand-edit-valid", async () => {
  const ta = page.locator('[data-testid="approval-params"] textarea, textarea').first();
  const n = await ta.count();
  let before = "", after = "";
  if (n) { before = await ta.inputValue(); after = before.replace(/sto-3g/i, "6-31g"); await ta.fill(after); await page.waitForTimeout(800); }
  return { editable: n > 0, changed: before !== after, card: await card() };
});
await L.observe(page, "card-hand-edit-invalid", async () => {
  const ta = page.locator('[data-testid="approval-params"] textarea, textarea').first();
  if (await ta.count()) { const v = await ta.inputValue(); await ta.fill(v.replace(/6-31g/i, "not-a-basis-set")); await page.waitForTimeout(800); }
  return { card: await card(), error: await page.locator('[data-testid="approval-error"]').innerText().catch(() => null) };
});

// Stale card: ask for something else while the card is up.
await turn("stale-card-new-request", "Actually, forget that. What is the molecular weight of water?");
await L.observe(page, "stale-card-state", async () => ({ card: await card(), trace: await toolTrace() }));

// --- a clean approve, and the instant confirmation -------------------------------------
await turn("final-draft", "Single point HF/STO-3G on water with PySCF, please.");
await L.observe(page, "approve-and-time-confirmation", async () => {
  const t = Date.now();
  await page.locator('[data-testid="approval-approve"]').click();
  // How long until the UI acknowledges the click at all?
  await page.waitForFunction(() => !document.querySelector('[data-testid="approval-approve"]'), null, { timeout: 30000 }).catch(() => {});
  const gone_ms = Date.now() - t;
  await page.waitForTimeout(1500);
  return { card_gone_ms: gone_ms, reply_tail: (await transcript(page)).slice(-1200), trace: await toolTrace() };
});
await L.observe(page, "job-completes", async () => {
  // A trivial PySCF job finishes in seconds; wait for the summary.
  await page.waitForFunction(() => /completed|finished|energy/i.test(document.body.innerText.slice(-3000)), null, { timeout: 240000 }).catch(() => {});
  return { reply_tail: (await transcript(page)).slice(-2500), trace: await toolTrace(), console: page.__console.splice(0) };
});

fs.writeFileSync(path.join(L.shotDir, "requests.json"), JSON.stringify(page.__requests, null, 1));
await ctx.close(); await browser.close();
console.log(`\nevidence: ${L.file}\nscreenshots: ${L.shotDir}/`);
