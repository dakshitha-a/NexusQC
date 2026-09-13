// Shared driver for the Phase 3 live walkthrough of the September 2026 app
// review. Each P3.x step is its own script next to this file.
//
// This is NOT a pass/fail test suite. The scripts gather evidence -- a
// screenshot at each step, an inventory of what is on screen, timings, and
// the raw text the agent produced -- and write it under evidence/p3/. The
// judgement about what is a bug, a comfort gap or a slow path is made by a
// person looking at that evidence afterwards and writing entries into
// findings.md. `check()` is used only for things that are unambiguous, and a
// failed check is an observation to look at, not a verdict.
//
// Everything reusable comes from tests/e2e/ui/_ui.mjs, which already knows
// the app's real login screen, how to wait out an in-flight agent turn, and
// how to read WebGL canvas pixels through toDataURL (page.screenshot cannot).
// Playwright resolves through that module's own node_modules symlink, so this
// file never imports "playwright" directly.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export * from "../../../../../tests/e2e/ui/_ui.mjs";
import { BASE_URL, newBrowser, newContext, uiLogin, canvasHasContent } from "../../../../../tests/e2e/ui/_ui.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const EVIDENCE = HERE;

// The review accounts live only in the session scratchpad, never in the repo.
// The scratchpad path is passed in, because it is session-specific.
export function accounts() {
  const p = process.env.QC_REVIEW_ACCOUNTS;
  if (!p || !fs.existsSync(p)) {
    throw new Error("QC_REVIEW_ACCOUNTS must point at the scratchpad's review-accounts.json");
  }
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

/** One evidence log per P3 step: a JSONL of observations, appended as they
 *  happen so a crashed run keeps what it saw. */
export class Log {
  constructor(step) {
    this.step = step;
    this.file = path.join(EVIDENCE, `${step}.jsonl`);
    this.shotDir = path.join(EVIDENCE, step);
    fs.mkdirSync(this.shotDir, { recursive: true });
    this.n = 0;
    this.t0 = Date.now();
  }
  write(obj) {
    const rec = { t_ms: Date.now() - this.t0, ...obj };
    fs.appendFileSync(this.file, JSON.stringify(rec) + "\n");
    return rec;
  }
  /** Time a named action, screenshot after it, record the result. The
   *  screenshot is what a person reviews; the inventory is for diffing. */
  async observe(page, name, fn, { inventory = true } = {}) {
    const idx = String(++this.n).padStart(2, "0");
    const t = Date.now();
    let result, error;
    try { result = await fn(); } catch (e) { error = String(e && e.message || e); }
    const elapsed_ms = Date.now() - t;
    const shot = path.join(this.shotDir, `${idx}-${name}.png`);
    try { await page.screenshot({ path: shot, fullPage: false }); } catch (e) { /* page may be gone */ }
    const rec = { idx, name, elapsed_ms, shot: path.relative(EVIDENCE, shot), result, error };
    if (inventory) rec.inventory = await inventoryOf(page).catch(() => null);
    this.write(rec);
    const mark = error ? "ERR " : "    ";
    console.log(`${mark}[${idx}] ${name}  ${elapsed_ms} ms${error ? "  <-- " + error.slice(0, 120) : ""}`);
    return rec;
  }
  note(text, extra = {}) {
    this.write({ note: text, ...extra });
    console.log(`     note: ${text}`);
  }
}

/** What is on screen that a user could act on, plus the visible text of any
 *  error or notice. Cheap to compute and good for spotting "the button is
 *  gone" or "an error appeared" across a sequence of steps. */
export async function inventoryOf(page) {
  return page.evaluate(() => {
    const vis = (el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
    };
    const buttons = Array.from(document.querySelectorAll("button, a[href], [role=button]"))
      .filter(vis)
      .map((b) => (b.getAttribute("title") || b.getAttribute("aria-label") || b.textContent || "").trim().slice(0, 40))
      .filter(Boolean);
    const inputs = Array.from(document.querySelectorAll("input, textarea, select")).filter(vis)
      .map((i) => `${i.tagName.toLowerCase()}:${i.getAttribute("placeholder") || i.getAttribute("aria-label") || i.type || ""}`);
    const testids = Array.from(document.querySelectorAll("[data-testid]")).filter(vis)
      .map((e) => e.getAttribute("data-testid"));
    const canvases = Array.from(document.querySelectorAll("canvas")).filter(vis).length;
    const errors = Array.from(document.querySelectorAll('[role=alert], [data-testid*="error"], .error'))
      .filter(vis).map((e) => e.textContent.trim().slice(0, 160));
    return {
      title: document.title,
      buttons: [...new Set(buttons)],
      inputs: [...new Set(inputs)],
      testids: [...new Set(testids)],
      canvases,
      errors,
      body_chars: document.body.innerText.length,
    };
  });
}

/** The chat transcript as the user sees it: every message bubble's text, in
 *  order. Used to read what the agent actually said. */
export async function transcript(page) {
  return page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll('[data-testid="chat-composer"]'));
    // Message bubbles have no testid; fall back to the chat pane's article-ish blocks.
    const pane = document.querySelector("main") || document.body;
    const text = pane.innerText;
    return text.length > 12000 ? text.slice(-12000) : text;
  });
}

/** Every canvas on the page and whether it drew anything. */
export async function allCanvases(page) {
  const n = await page.evaluate(() => document.querySelectorAll("canvas").length);
  const out = [];
  for (let i = 0; i < n; i++) out.push(await canvasHasContent(page, "canvas", i));
  return out;
}

/** Log in as one of the review accounts through the real UI and return the
 *  page. Each call gets a fresh context, so nothing leaks between steps. */
export async function loginAs(browser, who, { clearStorage = true } = {}) {
  const acct = accounts()[who];
  if (!acct) throw new Error(`no review account named ${who}`);
  const ctx = await newContext(browser);
  if (clearStorage) {
    await ctx.addInitScript(() => {
      try {
        if (!sessionStorage.getItem("__p3_cleared__")) {
          localStorage.removeItem("qc-agent-layout");
          localStorage.removeItem("qc-agent-active-thread");
          sessionStorage.setItem("__p3_cleared__", "1");
        }
      } catch (e) { /* nothing to clear */ }
    });
  }
  const page = await ctx.newPage();
  // Console errors are evidence in their own right.
  page.__console = [];
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") page.__console.push(`${m.type()}: ${m.text().slice(0, 200)}`); });
  page.on("pageerror", (e) => page.__console.push(`pageerror: ${String(e).slice(0, 200)}`));
  // Every request, for the polling-volume measurements in P4.3.
  page.__requests = [];
  page.on("request", (r) => { const u = r.url(); if (u.includes("/api/")) page.__requests.push({ t: Date.now(), m: r.method(), u: u.replace(BASE_URL, "") }); });
  await uiLogin(page, acct.username, acct.password);
  return { ctx, page, acct };
}

export async function start() {
  const browser = await newBrowser();
  return browser;
}

export { BASE_URL };
