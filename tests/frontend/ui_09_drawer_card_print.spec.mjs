// The job drawer, the approval card and the Print theme, as found while
// taking the thesis screenshots on 2026-11-09:
//   - the drawer's bg-black/50 scrim dimmed and froze the chat about the job;
//   - the orbital table scrolled inside a fixed max-h-56 with room to spare;
//   - there was no theme with a white field and no scrollbars;
//   - the approval card's input box was a fixed 10 rows and a long note
//     pushed the card's head off screen.
//
// Runs against the stack (QC_AGENT_TEST_BASE_URL). To check a frontend
// change before it is deployed, start the Vite dev server and set
// QC_AGENT_TEST_VITE_URL; every non-/api request is then answered by it, so
// the API and the login origin are the stack's and the code is the new one.
// Two agent turns run on the stack's model. The one job they submit and the
// conversation are deleted at the end.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/ui_09_drawer_card_print.spec.mjs
import { createRequire } from "node:module";
import path from "node:path";
const HERE = path.dirname(new URL(import.meta.url).pathname);
const require = createRequire(path.join(HERE, "../../frontend/package.json"));
const { chromium } = require("playwright");
const H = await import(path.join(HERE, "_helpers.mjs"));
// The stack refuses a login from any origin but its own, so the browser
// talks to the stack's origin and every non-/api request is answered by the
// Vite dev server instead: real API, new frontend code.
const VITE = process.env.QC_AGENT_TEST_VITE_URL || null;
const BASE = H.BASE_URL;
const OUT = process.env.OUT;
const ORIGIN = { headers: { Origin: BASE } };
const results = [];
const check = (name, ok, detail = "") => { results.push([name, ok]); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${detail ? "  -- " + detail : ""}`); };

const browser = await H.newBrowser();
const ctx = await browser.newContext({ baseURL: BASE, ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
if (VITE) await ctx.route((url) => url.origin === new URL(BASE).origin && !url.pathname.startsWith("/api"), async (route) => {
  const u = new URL(route.request().url());
  const resp = await route.fetch({ url: VITE + u.pathname + u.search });
  await route.fulfill({ response: resp });
});
await ctx.addInitScript(() => {
  localStorage.setItem("qc-agent-appearance", JSON.stringify({
    state: { theme: "print", accent: "hbeta", fontScale: 1.35, density: "cosy", motion: "reduced" }, version: 0 }));
});
const page = await ctx.newPage();
const created = { thread: null, jobs: [] };
const jobsNow = async () => (await (await page.request.get(`${BASE}/api/jobs?include_archived=true`)).json()).map((j) => j.job_id);

async function turnDone(timeoutMs = 600000) {
  const thinking = page.locator('[data-testid="agent-thinking"]');
  await thinking.first().waitFor({ timeout: 15000 }).catch(() => undefined);
  const end = Date.now() + timeoutMs; let quiet = 0;
  while (Date.now() < end) {
    const busy = (await thinking.count()) || !(await page.locator('[data-testid="chat-send"]').count());
    if (busy) quiet = 0; else if (!quiet) quiet = Date.now(); else if (Date.now() - quiet > 3000) return;
    await page.waitForTimeout(400);
  }
  throw new Error("turn did not finish");
}
async function say(text) {
  await page.waitForSelector('[data-testid="chat-composer"]:not([disabled])', { timeout: 300000 });
  await page.fill('[data-testid="chat-composer"]', text);
  await page.press('[data-testid="chat-composer"]', "Enter");
}

try {
  await page.goto("/", { waitUntil: "networkidle" });
  if (!(await page.locator(H.LOGGED_IN).count())) {
    await page.fill('input[placeholder="Username or email"]', H.ADMIN_USER);
    await page.fill('input[type="password"]', H.adminPassword());
    await page.click('[data-testid="auth-submit"]');
    await page.waitForSelector(H.LOGGED_IN, { timeout: 20000 });
  }
  const hint = page.locator('[data-testid="first-run-hint-dismiss"]');
  if (await hint.isVisible().catch(() => false)) await hint.click();
  const before = await jobsNow();

  // ---- P4.3 Print theme ---------------------------------------------------
  const look = await page.evaluate(() => {
    const cs = getComputedStyle(document.body);
    const probe = document.createElement("div"); probe.className = "text-text-muted"; document.body.appendChild(probe);
    const muted = getComputedStyle(probe).color; probe.remove();
    return { theme: document.documentElement.dataset.theme, bg: cs.backgroundColor, text: cs.color, muted,
             sw: getComputedStyle(document.querySelector("main") || document.body).scrollbarWidth };
  });
  check("print theme is applied", look.theme === "print", JSON.stringify(look));
  check("white field", look.bg === "rgb(255, 255, 255)", look.bg);
  check("near-black text", look.text === "rgb(17, 20, 24)", look.text);
  check("dark muted text", look.muted === "rgb(58, 63, 71)", look.muted);
  check("scrollbars hidden", look.sw === "none", look.sw);
  await page.click('[data-testid^="rail-appearance"]');
  const swatch = page.locator('[data-testid="appearance-theme-print"]');
  check("Print is offered in the theme picker", await swatch.isVisible().catch(() => false));
  if (OUT) await page.screenshot({ path: `${OUT}/appearance.png` });
  await page.keyboard.press("Escape");

  // ---- conversation ------------------------------------------------------
  const r = await page.request.post(`${BASE}/api/threads`, { ...ORIGIN, data: { label: "fe verify (qatest)" } });
  created.thread = (await r.json()).thread_id;
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(H.LOGGED_IN, { timeout: 20000 });
  const row = page.locator(`[data-testid="conversation-row-${created.thread}"]`);
  if (!(await row.isVisible().catch(() => false))) await page.click('[title="Expand sidebar"]').catch(() => {});
  await row.click();
  await page.waitForTimeout(800);

  // ---- P4.4 approval card -------------------------------------------------
  await say("Compute the UV/Vis spectrum of formaldehyde with TDDFT at B3LYP/def2-SVP, 10 excited states, on ORCA.");
  await turnDone();
  const approve = page.locator('[data-testid="approval-approve"]');
  await approve.waitFor({ timeout: 300000 });
  const card = await page.evaluate(() => {
    const ta = document.querySelector('[data-testid="approval-approve"]').closest("div.rounded, section, article")?.parentElement?.querySelector("textarea")
      || document.querySelector("textarea");
    const notes = document.querySelector('[data-testid="approval-notes"]');
    return {
      lines: ta ? ta.value.split("\n").length : null, rows: ta?.rows,
      taScroll: ta ? ta.scrollHeight - ta.clientHeight : null,
      notesH: notes?.getBoundingClientRect().height ?? null,
      toggle: !!document.querySelector('[data-testid="approval-notes-toggle"]'),
      noteChars: notes ? notes.textContent.replace(/Show (all|less)$/, "").length : 0,
      gradientNote: !!notes && /excited-state gradient/i.test(notes.textContent),
    };
  });
  check("the input box shows every line without an inner scroll", card.taScroll !== null && card.taScroll <= 2, JSON.stringify(card));
  // A plain TDDFT card no longer carries the B88 gradient note (fixed in
  // the same tracker), so its notes are usually short. The fold is checked
  // against what is there: a toggle exactly when the notes are long.
  check("no excited-state gradient note on a plain TDDFT card", !card.gradientNote, JSON.stringify(card));
  check("notes fold behind Show all exactly when they are long",
        card.toggle === (card.noteChars > 240), JSON.stringify(card));
  if (OUT) await page.screenshot({ path: `${OUT}/approval_card.png` });
  if (card.toggle) {
    await page.click('[data-testid="approval-notes-toggle"]');
    const opened = await page.evaluate(() => document.querySelector('[data-testid="approval-notes"]').getBoundingClientRect().height);
    check("Show all unfolds it", opened > card.notesH, `${card.notesH} -> ${opened}`);
  }
  await page.click('[data-testid="approval-reject"]');
  await turnDone();

  // ---- P4.1 / P4.2 drawer -------------------------------------------------
  await say("Drop that draft. Then run an HF/STO-3G single point energy on water with PySCF.");
  await turnDone();
  await approve.waitFor({ timeout: 300000 });
  await approve.click();
  await turnDone();
  let jobId = null;
  for (let i = 0; i < 120 && !jobId; i++) {
    const fresh = (await jobsNow()).filter((j) => !before.includes(j));
    created.jobs = fresh;
    for (const j of fresh) {
      const st = await (await page.request.get(`${BASE}/api/jobs/${j}`)).json();
      if (st.status === "completed") jobId = j;
    }
    if (!jobId) await page.waitForTimeout(3000);
  }
  check("the water job completed", !!jobId, String(created.jobs));
  await page.waitForTimeout(2500);
  await page.click(`[data-testid="job-row-${jobId}"]`);
  await page.waitForSelector('[role="dialog"]', { timeout: 20000 });
  await page.waitForTimeout(1500);
  const scrim = await page.evaluate(() => [...document.querySelectorAll(".fixed.inset-0")].map((e) => getComputedStyle(e).backgroundColor));
  check("no scrim over the chat", !scrim.some((c) => c !== "rgba(0, 0, 0, 0)" && c !== "transparent"), JSON.stringify(scrim));

  const orb = page.getByText(/Molecular orbitals/i).first();
  await orb.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(600);
  const table = await page.evaluate(() => {
    const t = document.querySelector('[data-testid^="orbital-row-"]')?.closest("table");
    const wrap = t?.parentElement;
    return wrap ? { sh: wrap.scrollHeight, ch: wrap.clientHeight, rows: t.querySelectorAll("tbody tr").length } : null;
  });
  check("the orbital table has no inner scroll", table && table.sh - table.ch <= 2, JSON.stringify(table));
  if (OUT) await page.screenshot({ path: `${OUT}/drawer.png` });

  // Chat still scrolls with the drawer open: wheel over the chat column.
  const scroller = await page.evaluateHandle(() => {
    const els = [...document.querySelectorAll("*")].filter((e) => {
      const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
      return r.left < 700 && r.width > 300 && /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 20;
    });
    return els[0] || null;
  });
  if (await scroller.evaluate((e) => !!e)) {
    await scroller.evaluate((e) => { e.scrollTop = e.scrollHeight; });
    const top0 = await scroller.evaluate((e) => e.scrollTop);
    const box = await scroller.evaluate((e) => { const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    await page.mouse.move(box.x, box.y);
    await page.mouse.wheel(0, -400);
    await page.waitForTimeout(500);
    const top1 = await scroller.evaluate((e) => e.scrollTop);
    check("the chat scrolls while the drawer is open", top1 < top0, `${top0} -> ${top1}`);
  } else {
    check("the chat scrolls while the drawer is open", false, "no scrollable chat column found");
  }

  // The drawer is non-modal now, so a flyout it opens must not count as a
  // click outside it. The geometry flyout, because every single-geometry job
  // has one (a PySCF job has no raw input or output file).
  const geo = page.locator('[title="View geometry"]');
  check("the drawer offers its geometry flyout", (await geo.count()) > 0);
  if (await geo.count()) {
    await geo.first().click();
    const inFlyout = page.locator('[data-testid="flyout-download-geometry"]');
    await inFlyout.waitFor({ timeout: 10000 });
    const box = await inFlyout.boundingBox();
    // A click on the flyout's own surface, beside its download button, and
    // proof that the point is the flyout's rather than the drawer's.
    const px = box.x - 40, py = box.y + box.height / 2;
    const inside = await page.evaluate(([x, y]) => {
      const btn = document.querySelector('[data-testid="flyout-download-geometry"]');
      const panel = btn.closest('[role="dialog"]') || btn.parentElement.parentElement;
      const drawer = document.querySelector('[data-testid="drawer-send-copy"]').closest('[role="dialog"]');
      const hit = document.elementFromPoint(x, y);
      return { inPanel: !!hit && panel.contains(hit), panelIsDrawer: panel === drawer };
    }, [px, py]);
    check("the test click lands on the flyout, not the drawer",
          inside.inPanel && !inside.panelIsDrawer, JSON.stringify(inside));
    await page.mouse.click(px, py);
    await page.waitForTimeout(500);
    check("clicking inside the flyout keeps the drawer open",
          (await page.locator('[data-testid="drawer-send-copy"]').count()) === 1);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(500);
    check("Escape closes the flyout first and leaves the drawer",
          (await inFlyout.count()) === 0 &&
          (await page.locator('[data-testid="drawer-send-copy"]').count()) === 1);
  }
  await page.keyboard.press("Escape");
  await page.waitForTimeout(600);
  const stillOpen = await page.locator('[data-testid="drawer-send-copy"]').count();
  check("Escape closes the drawer", stillOpen === 0, String(stillOpen));
} catch (e) {
  check("script ran to the end", false, String(e).slice(0, 300));
  if (OUT) await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {});
} finally {
  const after = await jobsNow().catch(() => []);
  const before2 = new Set(created.jobs);
  for (const j of after) if (before2.has(j)) await page.request.delete(`${BASE}/api/jobs/${j}`, ORIGIN).catch(() => {});
  if (created.thread) await page.request.delete(`${BASE}/api/threads/${created.thread}`, ORIGIN).catch(() => {});
  const left = (await jobsNow().catch(() => [])).filter((j) => before2.has(j));
  check("created jobs and conversation deleted", left.length === 0, JSON.stringify(left));
  await browser.close();
  const nf = results.filter(([, ok]) => !ok).length;
  console.log(`\n${results.length - nf}/${results.length} checks passed in this script.`);
  process.exitCode = nf ? 1 : 0;
}
