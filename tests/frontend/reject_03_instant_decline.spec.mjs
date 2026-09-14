/**
 * Declining a job is answered immediately, in a real browser.
 *
 * The sibling of submit_02_instant_confirmation.spec.mjs, and the same
 * split of responsibilities. tests/backend/reject_01_decline_message.py
 * pins the graph contract, that no model turn runs after a decline. This is
 * the statement a user would make: the click is answered at once, and the
 * answer names what they turned down.
 *
 * It has to be a browser test. The message is written by a graph node
 * mid-run and published over SSE as an ordinary `message` event, so whether
 * it paints depends on the frontend's dispatch, and the wait it removes was
 * specifically a wait in front of an EMPTY pane: JobApprovalCard's onMutate
 * dismisses the card the instant the button is clicked, without waiting for
 * the server, so before this change the user was left looking at nothing at
 * all for the length of a model turn after acting themselves.
 *
 * The timing assertion is loose on purpose, for the reason submit_02 gives:
 * what is being distinguished is "the app wrote this" from "the served
 * model wrote this", and on this host those differ by two orders of
 * magnitude. A tight bound would fail because the shared GPU was busy.
 *
 * Raw Playwright, chromium, headless, no @playwright/test runner, same as
 * the rest of tests/frontend.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/reject_03_instant_decline.spec.mjs
 */
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, summary,
} from "./_helpers.mjs";

// Anything above this and the message cannot have come from the app.
const DECLINE_BUDGET_MS = 10000;

async function send(page, text) {
  const box = page.locator("textarea").first();
  await box.fill(text);
  await box.press("Enter");
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_reject03_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();

  try {
    console.log("\n== register + log in ==");
    await page.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
    await page.fill('input[placeholder="Email"]', `${username}@example.test`);
    await page.fill('input[placeholder="Username"]', username);
    await page.fill('input[placeholder="First name"]', "QA");
    await page.fill('input[placeholder="Last name"]', "Tester");
    await page.fill('input[placeholder="Password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 15000 });
    check("registered and logged in", true);

    // The baseline the rejection is measured against. See the delta check at
    // the end of this spec for why an absolute count will not do.
    const jobsBefore = await (async () => {
      const r = await page.request.get(`${BASE_URL}/api/jobs`, { headers: { Origin: BASE_URL } });
      const p0 = await r.json();
      return (Array.isArray(p0) ? p0 : (p0.jobs || [])).length;
    })();
    console.log(`   job list holds ${jobsBefore} row(s) before anything is drafted`);

    console.log("\n== drive a draft to an approval card ==");
    // Everything stated at once. With run_when_ready the card should come
    // up without a separate submit turn, which is the other half of this
    // change; the elicitation fallback below keeps the test honest if the
    // model asks a question anyway.
    await send(page, "Run a single point energy calculation on water with HF and the sto-3g basis.");
    const card = page.locator("text=/Approve .* job/").first();
    try {
      await card.waitFor({ timeout: 240000 });
    } catch {
      await send(page, "Use HF with the sto-3g basis.");
      await card.waitFor({ timeout: 240000 });
    }
    check("the approval card is up", true);

    console.log("\n== decline, and time the answer ==");
    const reject = page.locator("button", { hasText: /^(Reject|Decline)/ }).first();
    const t0 = Date.now();
    await reject.click();

    await page.waitForFunction(
      () => /Nothing was run/i.test(document.body.innerText),
      undefined,
      { timeout: 60000 },
    );
    const elapsed = Date.now() - t0;
    check(`the answer appears in ${(elapsed / 1000).toFixed(2)}s, under the ${DECLINE_BUDGET_MS / 1000}s budget`,
          elapsed < DECLINE_BUDGET_MS, `${elapsed}ms`);

    const body = await page.innerText("body");
    const line = (body.split("\n").find((l) => /Nothing was run/i.test(l)) || "").trim();
    check("it names what was turned down", /water/i.test(line), line);
    check("it invites a change rather than closing the exchange", /change/i.test(line), line);
    // resolve_job_label is what keeps the internal taxonomy out of this.
    check("it does not leak an internal task identifier",
          !/single_point|subtype|params=/.test(line), line);

    console.log("\n== nothing was submitted, and the turn ended ==");
    // A DELTA, not an absolute count. A job with no recorded owner is
    // deliberately visible to every user (app/auth/ownership.py's
    // unowned-means-shared rule, which is a settled decision rather than a
    // gap), so a brand-new account's job list is only empty on a deployment
    // that happens to hold no unowned jobs. This asserted emptiness and
    // passed for exactly as long as that was true by luck: at the 2026-09
    // gate the stack held five and the check reported a rejection that had
    // created five jobs, which it had not.
    const jobs = await page.request.get(`${BASE_URL}/api/jobs`, { headers: { Origin: BASE_URL } });
    const payload = await jobs.json();
    const rows = Array.isArray(payload) ? payload : (payload.jobs || []);
    const added = rows.length - jobsBefore;
    check("rejecting created no job", added === 0,
          `${jobsBefore} before, ${rows.length} after: ${JSON.stringify(rows).slice(0, 200)}`);

    await page.waitForFunction(
      () => {
        const t = document.querySelector("textarea");
        return t && !t.disabled;
      },
      undefined,
      { timeout: 30000 },
    );
    check("the composer is usable again", true);
    check("the approval card is gone",
          !/Approve\s+\S+\s+job/.test(await page.innerText("body")));
  } catch (err) {
    check("the run completed without throwing", false, String(err).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    // Nothing ran, so there are no jobs to remove. Deleting the account
    // takes its conversation with it, which is what keeps a run of this
    // from leaving qatest_* threads behind.
    await deleteUserByUsername(adminCtx, username);
    await browser.close();
  }

  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main();
