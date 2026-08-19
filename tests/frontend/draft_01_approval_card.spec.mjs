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
 * Raw Playwright, chromium, headless -- no @playwright/test runner, same
 * convention as the rest of tests/frontend.
 *
 * Run with the backend on :8000 and vite on :5173:
 *   node tests/frontend/draft_01_approval_card.spec.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.NEXUSQC_BASE_URL ?? "http://localhost:5173";
let pass = 0;
let fail = 0;

function check(label, ok, detail = "") {
  if (ok) {
    pass += 1;
    console.log(`  [PASS] ${label}`);
  } else {
    fail += 1;
    console.log(`  [FAIL] ${label}${detail ? `\n         ${detail}` : ""}`);
  }
}

async function send(page, text) {
  const box = page.locator("textarea").first();
  await box.fill(text);
  await box.press("Enter");
}

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
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
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("textarea", { timeout: 30000 });
    check("the app loads", true);

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
    // The auth endpoints answer 401/403 by design when no database is
    // configured -- that is this deployment being auth-less, not a break.
    // `/@fs/` 403s are a worktree artefact, not an app fault: when
    // node_modules is symlinked in from another checkout, Vite refuses to
    // serve files resolving outside its own root, and the only casualties
    // are webfonts. In a normal checkout these do not appear at all.
    const broken = failedRequests.filter(
      (r) => !/favicon|\/api\/auth\/|\/api\/admin\/|\/@fs\//.test(r),
    );
    check("no unexpected failing requests", broken.length === 0,
          broken.slice(0, 5).join(" | "));
  } catch (err) {
    check(`the run completed without throwing`, false, String(err).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    await browser.close();
  }

  console.log(`\n${pass}/${pass + fail} checks passed`);
  if (fail) {
    console.log(`[FAIL] ${fail} check(s) failed`);
    process.exit(1);
  }
  console.log("[PASS] ALL CHECKS PASSED");
}

main();
