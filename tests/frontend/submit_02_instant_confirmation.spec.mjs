/**
 * Approving a job confirms it immediately, in a real browser.
 *
 * The backend contract is pinned by tests/backend/submit_01_confirmation.py,
 * which proves no model turn runs after a submission. That is a statement
 * about the graph. This is the statement a user would make: the click is
 * answered at once, and the answer names the job.
 *
 * It is a browser test rather than another API test because what changed is
 * something only a browser shows. The confirmation is written by a graph
 * node mid-run and published over SSE as an ordinary `message` event, so
 * whether it actually paints depends on the frontend's message dispatch
 * (MessageBubbleRow renders an AIMessage carrying an unknown `notice` kind
 * as a plain assistant bubble) and on the turn ending cleanly enough to
 * re-enable the composer. CLAUDE.md is explicit that a code read is not
 * verification here.
 *
 * The timing assertion is deliberately loose. What is being distinguished
 * is "the app wrote this" from "the served model wrote this", and on this
 * host those differ by two orders of magnitude: the approval resume was
 * measured at a 0.10s median after this change against a 21.3s median
 * before it, with the old path ranging to 95s under load. A ceiling of 10s
 * therefore separates the two cases without ever failing because the
 * machine was busy, which a tight bound on a shared GPU host would.
 *
 * Raw Playwright, chromium, headless -- no @playwright/test runner, same
 * convention as the rest of tests/frontend.
 *
 * Run against the docker-compose dev stack (needs `npm run build` to have
 * refreshed nginx's bind-mounted frontend/dist first -- see CLAUDE.md):
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/submit_02_instant_confirmation.spec.mjs
 */
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, summary,
} from "./_helpers.mjs";

// Anything above this and the message cannot have come from the app.
const CONFIRM_BUDGET_MS = 10000;

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
  const username = "qatest_submit02_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const jobIds = [];

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

    console.log("\n== drive a draft to an approval card ==");
    await send(page, "Run a single point energy calculation on water.");
    await page.waitForFunction(
      () => document.body.innerText.includes("level of theory")
         || document.body.innerText.includes("basis set"),
      undefined,
      { timeout: 180000 },
    );
    await send(page, "Use HF with the sto-3g basis.");
    const card = page.locator("text=/Approve .* job/").first();
    await card.waitFor({ timeout: 240000 });
    check("the approval card is up", true);

    console.log("\n== approve, and time the confirmation ==");
    const approve = page.locator("button", { hasText: /^Approve/ }).first();
    const t0 = Date.now();
    await approve.click();

    // "Started " opens the app-written confirmation. Matching on that
    // rather than on a job id keeps this readable, and the id is asserted
    // separately below.
    await page.waitForFunction(
      () => /\bStarted\b/.test(document.body.innerText),
      undefined,
      { timeout: 60000 },
    );
    const elapsed = Date.now() - t0;
    check(`the confirmation appears in ${(elapsed / 1000).toFixed(2)}s, under the ${CONFIRM_BUDGET_MS / 1000}s budget`,
          elapsed < CONFIRM_BUDGET_MS, `${elapsed}ms`);

    const body = await page.innerText("body");
    const line = (body.split("\n").find((l) => /\bStarted\b/.test(l)) || "").trim();
    check("it names the molecule", /water/i.test(line), line);
    check("it names the level of theory the Job Manager would", /sto-3g/i.test(line), line);
    check("it gives the user a job id", /Job id\s+[0-9a-f]{6,}/i.test(line), line);
    // The whole point of routing the text through resolve_job_label: a
    // chemist reads this, so the internal taxonomy must not leak.
    check("it does not leak an internal task identifier",
          !/single_point|subtype|params=/.test(line), line);

    const idMatch = line.match(/Job id\s+([0-9a-f]{6,})/i);
    if (idMatch) jobIds.push(idMatch[1]);

    console.log("\n== the turn really ended ==");
    // turnInProgress gates the composer, so a re-enabled textarea is the
    // observable form of "the graph stopped", which is what the change
    // actually did.
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
    // Leave no jobs behind, per the standing rule that a suite run does not
    // clutter the job list.
    for (const id of jobIds) {
      try {
        await page.request.delete(`${BASE_URL}/api/jobs/${id}`, { headers: { Origin: BASE_URL } });
      } catch {}
    }
    await deleteUserByUsername(adminCtx, username);
    await browser.close();
  }

  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main();
