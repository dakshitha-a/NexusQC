// P3.10 failure paths, P3.11 documentation accuracy against the running app,
// P3.12 layout / keyboard / contrast. One driver: 10 and 12 are UI-side and
// 11 walks the doc-claims checklist, all as qa_review.
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_10_12_failures_docs_layout.mjs
import fs from "node:fs";
import path from "node:path";
import { start, loginAs, Log, sendMessage, transcript, BASE_URL } from "./_p3.mjs";

const L = new Log("p3_10_12_failures_docs_layout");
const browser = await start();
const { ctx, page } = await loginAs(browser, "qa_review");

async function turn(name, text, { timeout = 300000 } = {}) {
  return L.observe(page, name, async () => {
    const t = Date.now();
    await sendMessage(page, text, { timeout });
    return { turn_ms: Date.now() - t, reply_tail: (await transcript(page)).slice(-2000), card: await page.locator('[data-testid="approval-approve"]').count() > 0 };
  });
}
async function reject() { const r = page.locator('[data-testid="approval-reject"]'); if (await r.count()) { await r.click(); await page.waitForTimeout(1500); } }

// ===== P3.10: failure paths =================================================
await L.observe(page, "p10-new-conv", async () => { const b = page.locator('[data-testid="conversation-new"]'); if (await b.count()) await b.click(); await page.waitForTimeout(600); return {}; }, { inventory: false });
// A basis ORCA rejects: does the failure notice card appear, and does
// troubleshoot work?
await turn("p10-bad-basis", "Run an HF single point on water with ORCA using the basis set 'not-a-real-basis'.");
await L.observe(page, "p10-approve-bad-basis", async () => {
  if (await page.locator('[data-testid="approval-approve"]').count()) await page.locator('[data-testid="approval-approve"]').click();
  await page.waitForTimeout(15000);
  const failCard = await page.evaluate(() => /fail|error|could not|did not/i.test(document.body.innerText.slice(-2000)));
  const troubleshoot = await page.locator('[data-testid*="troubleshoot"], button:has-text("Troubleshoot")').count();
  return { failure_notice_visible: failCard, troubleshoot_control: troubleshoot > 0, reply_tail: (await transcript(page)).slice(-1500) };
});
// A nonsense molecule name.
await turn("p10-nonsense-molecule", "Load the molecule qwertyuiop as the active structure.");
await reject();
// An upload over the limit: attempt a large file and read the response.
await L.observe(page, "p10-oversize-upload", async () => {
  const big = path.join(L.shotDir, "big.xyz");
  const line = "H 0.0 0.0 0.0\n";
  fs.writeFileSync(big, "100000\nbig\n" + line.repeat(100000));
  const r = await ctx.request.post(`${BASE_URL}/api/uploads`, { multipart: { file: { name: "big.xyz", mimeType: "chemical/x-xyz", buffer: fs.readFileSync(big) } } });
  fs.rmSync(big, { force: true });
  return { status: r.status(), body: (await r.text()).slice(0, 300) };
}, { inventory: false });
// Stop a turn mid-stream.
await turn("p10-start-long-turn", "Set the molecule to caffeine and give me a detailed multi-paragraph explanation of its electronic structure, then propose five calculations.", { timeout: 8000 }).catch(() => L.note("long turn still streaming, as intended"));
await L.observe(page, "p10-stop-button", async () => {
  const stop = page.locator('[title="Stop"], [data-testid="chat-header-running"]').first();
  const found = await stop.count();
  if (found) { await stop.click().catch(() => {}); await page.waitForTimeout(2000); }
  return { stop_control_found: found > 0, reply_tail: (await transcript(page)).slice(-800) };
});

// ===== P3.11: documentation claims against the running app ===================
// Walk the high-priority rows of the doc-claims checklist that are cheap to
// check from a logged-in session. The checklist itself is committed at
// evidence/doc-claims.md; here we record the app's actual behaviour for the
// rows a script can settle, leaving prose rows to a human read.
await L.observe(page, "p11-doc-claims-machine-checkable", async () => {
  const results = {};
  // Claim: /api/health returns ok.
  results.health = (await ctx.request.get(`${BASE_URL}/api/health`)).status();
  // Claim: the capability matrix is queryable; does the job registry endpoint exist?
  results.job_registry = (await ctx.request.get(`${BASE_URL}/api/job-registry`)).status();
  // Claim (welcome screen): BAGEL can run scans. The registry says pes_1d is pyscf/orca only.
  results.note = "BAGEL-scan and AVAS-tutorial claims are checked in the walkthrough turns below and against doc-claims.md";
  return results;
}, { inventory: false });
await turn("p11-bagel-scan-claim", "Run a bond-scan potential energy surface of water on BAGEL.");
await reject();
await turn("p11-avas-claim", "Use AVAS to choose a CASSCF active space for water.");
await reject();

// ===== P3.12: layout, keyboard, contrast ====================================
for (const [w, h, label] of [[1024, 768, "1024"], [1280, 800, "1280"], [1920, 1080, "1920"], [400, 800, "phone"]]) {
  await L.observe(page, `p12-width-${label}`, async () => {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(600);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
    return { width: w, horizontal_overflow: overflow };
  });
}
await page.setViewportSize({ width: 1280, height: 800 });
// Keyboard: can the composer be reached and submitted by keyboard alone?
await L.observe(page, "p12-keyboard-composer", async () => {
  await page.keyboard.press("Tab"); await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => { const el = document.activeElement; return el ? `${el.tagName}.${el.className}`.slice(0, 60) : null; });
  return { focused_after_two_tabs: focused };
});
// Contrast: sample a few foreground/background pairs in the current theme.
await L.observe(page, "p12-contrast-sample", async () => {
  return page.evaluate(() => {
    function lum(c) { const m = c.match(/\d+/g); if (!m) return null; const [r, g, b] = m.map(Number).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; }
    function ratio(fg, bg) { const a = lum(fg), b = lum(bg); if (a == null || b == null) return null; const hi = Math.max(a, b) + 0.05, lo = Math.min(a, b) + 0.05; return +(hi / lo).toFixed(2); }
    const out = [];
    for (const el of Array.from(document.querySelectorAll("button, a, p, span, td")).slice(0, 40)) {
      const s = getComputedStyle(el); const bg = s.backgroundColor;
      if (bg === "rgba(0, 0, 0, 0)") continue;
      const r = ratio(s.color, bg);
      if (r != null && r < 4.5) out.push({ text: (el.textContent || "").trim().slice(0, 24), ratio: r, color: s.color, bg });
    }
    return { low_contrast_samples: out.slice(0, 15) };
  });
});

fs.writeFileSync(path.join(L.shotDir, "requests.json"), JSON.stringify(page.__requests, null, 1));
await ctx.close(); await browser.close();
console.log(`\nevidence: ${L.file}\nscreenshots: ${L.shotDir}/`);
