/**
 * P2.2/P2.5 -- the approval card still renders after the toolset rewrite.
 *
 * `submit_draft` replaced `submit_job`, and with it the payload the card
 * reads. The new payload is a superset -- `task`, `subtype` and
 * `capability_note` added, nothing removed -- so a code read says the card
 * is fine. CLAUDE.md is explicit that a code read is not verification
 * here: several real bugs in this app appeared only under real browser
 * interaction, and a card that silently renders empty looks exactly like
 * one that renders correctly to anything short of a browser.
 *
 * Driven through a real conversation against the served model rather than
 * by seeding a checkpoint, because what is being checked is the whole path
 * -- the model choosing the draft tools, the backend's questions arriving
 * as chat, submit_draft interrupting, the card painting, and Approve
 * POSTing successfully.
 *
 * P4.7: retargeted onto the shared docker-compose dev stack (BASE_URL from
 * _helpers.mjs, default :8444) with a real register+login, instead of a
 * hardcoded `:5173` literal assuming a bare/no-auth `npm run dev` + `python
 * -m server.main` pair -- the docker stack requires auth, which the old
 * bare-mode assumption never accounted for, and every other spec in this
 * directory already runs this way (see up_02_files_and_attach.spec.mjs).
 * This closes P2B.7's last outstanding suite gap: `npm run test:e2e` used
 * to report this spec as a documented, unfixed setup dependency rather
 * than a pass.
 *
 * Raw Playwright, chromium, headless -- no @playwright/test runner, same
 * convention as the rest of tests/frontend.
 *
 * Run against the real docker-compose dev stack (needs `npm run build` to
 * have refreshed nginx's bind-mounted frontend/dist first -- see
 * CLAUDE.md):
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/draft_01_approval_card.spec.mjs
 *
 * NOTE (open question, not settled by this step -- see docs/OVERHAUL_PLAN.md's
 * Phase 4 entry): whether the bare `:5173`+`:8000` dev-mode SSE drop
 * ("Lost connection to the server -- reconnecting...") P2B.7 documented is a
 * real product defect in the local `npm run dev` path, or an artifact of
 * that specific bare-process combination, is unresolved by this retarget --
 * it needs a human watching a real browser against that exact bare
 * combination to settle, which this automated spec (now pointed at the
 * docker stack instead) cannot determine either way.
 */
import {
  newBrowser, newContext, adminApiLogin, mintInvite, deleteUserByUsername, check, summary, BASE_URL,
} from "./_helpers.mjs";

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
  const username = "qatest_draft01_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  // "Failed to load resource" carries no URL in the console text, so the
  // request itself is recorded -- otherwise a real broken endpoint is
  // indistinguishable from a missing favicon.
  page.on("response", (r) => {
    if (r.status() >= 400) failedRequests.push(`${r.status()} ${r.url()}`);
  });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  try {
    console.log("\n== register + log in ==");
    await page.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
    await page.fill('input[placeholder="Email"]', `${username}@example.test`);
    await page.fill('input[placeholder="Username"]', username);
    await page.fill('input[placeholder="Password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 15000 });
    check("registered and logged in", true);

    console.log("\n== the draft conversation reaches an approval card ==");
    await send(page, "Run a geometry optimization on water.");
    // The backend's own question has to come back as chat, verbatim.
    // waitForFunction's real signature is (pageFunction, arg, options) --
    // an explicit `undefined` arg is required here, or a two-argument
    // call silently binds the options object as `arg` instead and every
    // wait below is capped at Playwright's 30s default regardless of the
    // timeout requested (confirmed empirically: a bare two-arg call with
    // a zero-parameter pageFunction still timed out at 30000ms).
    await page.waitForFunction(
      () => document.body.innerText.includes("level of theory")
         || document.body.innerText.includes("basis set"),
      undefined,
      { timeout: 180000 },
    );
    check("the backend's elicitation question is relayed into the chat", true);

    await send(page, "Use HF with the sto-3g basis.");
    const card = page.locator("text=/Approve .* job/").first();
    await card.waitFor({ timeout: 240000 });
    check("submit_draft paints the approval card", true);

    const body = await page.innerText("body");
    check("the card names the job type", /Approve\s+\S+\s+job/.test(body),
          body.slice(0, 200));
    check("and the molecule", /water/i.test(body));

    console.log("\n== the card's contents survived the payload change ==");
    // input_preview is the field the card is really for: a card that shows
    // no input is a card asking someone to approve nothing.
    const preview = await page.locator("pre, textarea").allInnerTexts();
    const previewText = preview.join("\n");
    check("the engine input is shown for approval",
          /pyscf|gto|mol\.basis/i.test(previewText), previewText.slice(0, 200));

    const approve = page.locator("button", { hasText: /^Approve/ }).first();
    check("an Approve button is present", await approve.count() > 0);

    console.log("\n== approving actually submits ==");
    const [response] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes("/approval") || r.url().includes("/approve"),
        { timeout: 60000 },
      ),
      approve.click(),
    ]);
    check(`the approval POST succeeds (got ${response.status()})`,
          response.status() >= 200 && response.status() < 300);

    await page.waitForFunction(
      () => !/Approve\s+\S+\s+job/.test(document.body.innerText),
      undefined,
      { timeout: 60000 },
    );
    check("and the card is dismissed once approved", true);

    console.log("\n== nothing broke quietly ==");
    const realErrors = consoleErrors.filter(
      (e) => !/favicon|ResizeObserver|Download the React DevTools|Failed to load resource/i.test(e),
    );
    check("no uncaught javascript errors", realErrors.length === 0,
          realErrors.slice(0, 3).join(" | "));
    // GET /api/auth/me 401s once, harmlessly, before login on every
    // anonymous page load (see up_02_files_and_attach.spec.mjs's own
    // comment on this) -- filtered by URL rather than assumed absent now
    // that this spec runs against the auth-requiring docker stack.
    const broken = failedRequests.filter((r) => !/favicon|\/api\/auth\/me/.test(r));
    check("no unexpected failing requests", broken.length === 0,
          broken.slice(0, 5).join(" | "));
  } catch (err) {
    check(`the run completed without throwing`, false, String(err).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    await deleteUserByUsername(adminCtx, username);
    await browser.close();
  }

  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main();
