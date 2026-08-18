// Shared setup for the tests/e2e/ui specs. Extends tests/frontend/_helpers.mjs
// with the things every UI spec in this pass needs, each derived from a
// confirmed constraint rather than guessed:
//
//  * localStorage keys `qc-agent-layout` and `qc-agent-active-thread`
//    persist panel collapse state and the selected conversation, so they
//    leak between runs unless cleared per context.
//  * The composer stays disabled until the SSE stream connects, so a spec
//    that types immediately after load silently does nothing.
//  * Radix dialogs portal to document.body -- they are NOT inside #root,
//    so locators must be page-scoped.
//  * page.screenshot() cannot capture WebGL canvas content; canvas pixel
//    assertions must go through canvas.toDataURL() in page.evaluate().
//  * page.waitForFunction's signature is (fn, ARG, options). Passing the
//    options object as the second argument makes it the ARG and silently
//    leaves the timeout at Playwright's 30s default -- which is how a call
//    written to allow 600s for a full LLM turn was in fact giving up after
//    30. Every call below therefore passes an explicit `null` arg.
//
// The app is thin on data-testids, so much of what follows is targeted by
// title=, visible text, or placeholder=. Several title values collide across
// components, so the helpers below scope them explicitly where needed.
//
// The one place to prefer a testid unconditionally is the account cogwheel and
// its menu entries: `has-text` is a case-insensitive SUBSTRING match, so
// `button:has-text("Admin")` once matched the username of any account called
// something like "qatest_admin". See UserMenu.tsx.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { BASE_URL, newBrowser, newContext, check, summary, randSuffix, adminPassword, ADMIN_USER, openUserMenu, LOGGED_IN } from "../../frontend/_helpers.mjs";

export { BASE_URL, newBrowser, newContext, check, summary, randSuffix, adminPassword, ADMIN_USER, openUserMenu, LOGGED_IN };

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const SHOT_DIR = path.join(__dirname, "..", "..", "..", "docs", "e2e-artifacts");

/** A context with the layout/thread localStorage cleared, so panel
 *  collapse state and the active conversation never leak between specs. */
export async function freshContext(browser) {
  const ctx = await newContext(browser);
  // addInitScript runs on EVERY navigation, including page.reload() -- so a
  // naive "clear localStorage" here silently wipes the very state a
  // persistence test is about to verify, and the app looks broken when it
  // is not. Guard with a sessionStorage sentinel: sessionStorage survives a
  // reload within the same tab, so the clear happens exactly once, on the
  // first load of the context.
  await ctx.addInitScript(() => {
    try {
      if (!sessionStorage.getItem("__e2e_cleared__")) {
        localStorage.removeItem("qc-agent-layout");
        localStorage.removeItem("qc-agent-active-thread");
        sessionStorage.setItem("__e2e_cleared__", "1");
      }
    } catch (e) { /* first-load, nothing to clear */ }
  });
  return ctx;
}

/** Log in through the real LoginScreen, not the API, so the auth UI is
 *  itself exercised on every spec that needs a session. */
export async function uiLogin(page, username, password) {
  await page.goto(`${BASE_URL}/`);
  await page.waitForSelector('input[placeholder="Username or email"]', { timeout: 30000 });
  await page.fill('input[placeholder="Username or email"]', username);
  await page.fill('input[placeholder="Password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 60000 });
}

/** Register through the real invite flow (?invite= prefills and switches
 *  LoginScreen into register mode). */
export async function uiRegister(page, token, username, email, password) {
  await page.goto(`${BASE_URL}/?invite=${encodeURIComponent(token)}`);
  await page.waitForSelector('input[placeholder="Invite token"]', { timeout: 30000 });
  await page.fill('input[placeholder="Email"]', email);
  await page.fill('input[placeholder="Username"]', username);
  await page.fill('input[placeholder="Password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 60000 });
}

/** The composer is disabled until chatStore.sseConnected flips true, so this
 *  waits for the textarea to become enabled. That is necessary but NOT
 *  sufficient to send: see sendMessage, which additionally waits on the Send
 *  button, whose disabled condition is a different expression. */
export async function waitForComposerReady(page, timeout = 60000) {
  await page.waitForSelector('textarea', { timeout });
  await page.waitForFunction(() => {
    const ta = document.querySelector("textarea");
    return ta && !ta.disabled;
  }, null, { timeout });
}

/** Send a chat message and wait for the turn to settle. Returns when the
 *  composer is re-enabled (turn complete) or an approval card appears. */
export async function sendMessage(page, text, { timeout = 600000 } = {}) {
  await waitForComposerReady(page);
  // Wait out any turn already in flight -- very often one THIS SPEC did not
  // start. A spec opens whatever thread is active, and the previous spec's
  // last turn can still be streaming there: sendMessage returns once the
  // composer re-enables, which is not the same instant the agent finishes.
  // While a turn runs, Composer.tsx renders a Stop button INSTEAD of Send, so
  // `[title="Send"]` is absent from the DOM entirely -- and waiting for it to
  // become *enabled* then spins against an element that does not exist, which
  // is exactly the shape of the 3-minute hang this replaced. Waiting for it to
  // EXIST is how you wait for someone else's turn to end.
  await page.waitForSelector('[title="Send"]', { timeout });
  await page.fill("textarea", text);
  // Wait on the SEND BUTTON, not just the textarea. They do not share a
  // disabled condition -- Composer.tsx gates the button on
  // `disabled || !text.trim()` -- so an SSE reconnect landing between
  // waitForComposerReady and this click leaves the textarea enabled and the
  // button not. Playwright then burns its 30s default ACTION timeout waiting
  // for actionability and fails with a bare TimeoutError that looks like the
  // app hung. Confirmed from a real failure log: `<button disabled
  // title="Send">`, 58 retries, textarea fine throughout. Rare on an idle
  // host, near-certain across several consecutive turns on a loaded one.
  await page.waitForFunction(() => {
    const b = document.querySelector('[title="Send"]');
    return b && !b.disabled;
  }, null, { timeout: 180000 });
  await page.click('[title="Send"]');
  await page.waitForFunction(() => {
    const ta = document.querySelector("textarea");
    const approving = document.body.innerText.includes("Approve & run");
    return approving || (ta && !ta.disabled);
  }, null, { timeout });
}

/** WebGL canvases render nothing that page.screenshot() can capture.
 *  This pulls actual pixels out of the GL context and reports whether the
 *  canvas drew anything at all (non-uniform pixel content), which is the
 *  only automatable "did the 3D view render" assertion available. */
export async function canvasHasContent(page, selector = "canvas", index = 0) {
  return page.evaluate(({ selector, index }) => {
    const canvases = Array.from(document.querySelectorAll(selector));
    const c = canvases[index];
    if (!c) return { found: false };
    let dataUrl = "";
    try {
      dataUrl = c.toDataURL();
    } catch (e) {
      return { found: true, error: String(e) };
    }
    return {
      found: true,
      count: canvases.length,
      width: c.width,
      height: c.height,
      bytes: dataUrl.length,
      // A blank canvas serializes to a very short data URL; a rendered
      // molecule is orders of magnitude larger.
      looksRendered: dataUrl.length > 5000,
    };
  }, { selector, index });
}

export async function shot(page, name) {
  const fs = await import("node:fs");
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const file = path.join(SHOT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  return file;
}

/** Several title= values are shared with NON-interactive divs in the
 *  collapsed rail/dock (e.g. "Molecule", "Jobs", "Conversations"). This
 *  restricts a title lookup to real controls. */
export function control(page, title) {
  return page.locator(`button[title="${title}"], a[title="${title}"]`);
}
