// The failed-job notice renders as a card with a Troubleshoot button, and
// pressing it starts the investigation.
//
//   QC_AGENT_TEST_BASE_URL=http://127.0.0.1:5173 \
//     node tests/frontend/fail_01_notice_card.spec.mjs
//
// Raw playwright (chromium), no @playwright/test runner -- house style, see
// tests/README.md.
//
// This is the browser half of the auto-retry removal. tests/backend/
// fail_01_notice_flow.py proves the backend writes a persisted notice and
// starts no agent turn; this proves a user actually SEES it and can act on
// it. CLAUDE.md requires a real browser for frontend changes because a code
// read has silently missed real bugs here before.
//
// The load-bearing part is the reload: the notice must survive it. A user
// who submits a long calculation and closes the tab is the normal case, not
// the edge case, so a notice that lived only in an SSE event would be
// invisible to exactly the person it is for.
//
// Runs against a dev stack with auth unconfigured (bare `python -m
// server.main` + `npm run dev`), which is the local-dev path where
// /api/job-registry and the thread routes are open.
import { chromium } from "playwright";

const BASE_URL = process.env.QC_AGENT_TEST_BASE_URL || "http://127.0.0.1:5173";
const THREAD_ID = process.env.QC_AGENT_TEST_THREAD_ID;
const JOB_ID = process.env.QC_AGENT_TEST_JOB_ID;
// The app has no thread deep-link, so the conversation is opened by
// clicking its label in the sidebar -- which is also closer to what a user
// coming back to a finished job actually does.
const THREAD_LABEL = process.env.QC_AGENT_TEST_THREAD_LABEL || "qatest_notice";

const results = [];
function check(name, condition, detail = "") {
  const status = condition ? "PASS" : "FAIL";
  console.log(`  [${status}] ${name}${detail ? ` -- ${detail}` : ""}`);
  results.push([name, condition]);
  return condition;
}

const NOTICE = 'text=Job failed';
const TROUBLESHOOT = 'button:has-text("Troubleshoot")';

async function main() {
  if (!THREAD_ID || !JOB_ID) {
    console.log("[FAIL] QC_AGENT_TEST_THREAD_ID and QC_AGENT_TEST_JOB_ID must be set "
      + "(the harness creates the failed job before launching this spec).");
    return 1;
  }

  const browser = await chromium.launch({ ignoreHTTPSErrors: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true, baseURL: BASE_URL });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

  try {
    console.log("\n== the notice renders as a card ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(NOTICE, { timeout: 30000 });
    check("a 'Job failed' notice card is visible", await page.isVisible(NOTICE));

    const body = await page.textContent("body");
    check("the notice names the failed job", body.includes(JOB_ID), JOB_ID);
    check("the notice says nothing was resubmitted",
      /haven't changed anything or resubmitted/i.test(body));

    check("a Troubleshoot button is offered", await page.isVisible(TROUBLESHOOT));

    console.log("\n== the notice survives a reload ==");
    // The whole reason jobs run detached is that a user can leave and come
    // back. A notice that did not survive this would be invisible to the
    // person most likely to hit a failure.
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(NOTICE, { timeout: 30000 });
    check("the notice is still there after a full page reload",
      await page.isVisible(NOTICE));
    check("the Troubleshoot button is still offered after reload",
      await page.isVisible(TROUBLESHOOT));

    console.log("\n== pressing Troubleshoot starts the investigation ==");
    const [response] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes(`/troubleshoot/${JOB_ID}`) && r.request().method() === "POST",
        { timeout: 20000 },
      ),
      page.click(TROUBLESHOOT),
    ]);
    check("the troubleshoot route was called", response.status() === 202,
      `status ${response.status()}`);
    // The button is replaced by a progress line: the action is one-shot,
    // so a user cannot fire three investigations by clicking three times.
    await page.waitForSelector("text=Looking at the engine's output", { timeout: 15000 });
    check("the card shows the investigation has started",
      await page.isVisible("text=Looking at the engine's output"));
    check("the Troubleshoot button is no longer offered (one-shot)",
      !(await page.isVisible(TROUBLESHOOT)));

    console.log("\n== no console errors ==");
    // Two known environmental artifacts are excluded, named individually
    // rather than filtered by a broad pattern -- a wide filter here would
    // quietly swallow a real error from this feature, which is the only
    // thing the check exists to catch.
    //
    //   * /api/auth/me 404s when the backend runs without a database, so
    //     the auth router is never mounted. That is the local-dev path
    //     this spec deliberately runs on.
    //   * font files 403 when frontend/node_modules is a symlink from
    //     outside the checkout (a git worktree), because Vite's fs
    //     allow-list refuses to serve through it. An artifact of how the
    //     dev server was started, not of the page.
    const ENVIRONMENTAL = [
      /\/api\/auth\/me/i,
      /status of 404/i,
      /status of 403/i,
      /favicon/i,
    ];
    const real = consoleErrors.filter((t) => !ENVIRONMENTAL.some((re) => re.test(t)));
    check("no console errors beyond the known environmental ones",
      real.length === 0, real.slice(0, 3).join(" | "));
    console.log(`     (${consoleErrors.length - real.length} environmental message(s) ignored: `
      + `auth-not-configured 404s and worktree font 403s)`);
  } catch (e) {
    check(`spec ran without throwing`, false, String(e).slice(0, 300));
  } finally {
    await browser.close();
  }

  const nFail = results.filter(([, ok]) => !ok).length;
  console.log(`\n${results.length - nFail}/${results.length} checks passed`);
  if (nFail > 0) {
    console.log(`[FAIL] ${nFail} check(s) failed`);
    return 1;
  }
  console.log("[PASS] ALL CHECKS PASSED");
  return 0;
}

process.exit(await main());
