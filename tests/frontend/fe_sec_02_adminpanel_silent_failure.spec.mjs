// FE-SEC-02: an admin action that fails on the server has to say so.
//
// This began as a bug report -- AdminPanel's five mutations had no
// onError/isError handling at all, so a 500 left the button quietly
// reverting with nothing shown. It is now the regression test for the fix:
// DangerZoneSection wires onError on every mutation and StorageSection
// renders "Purge failed: ...", so forcing a 500 must produce visible error
// text. A silent revert here means the handling has been lost again.
//
// It used to drive the public-access toggle, which was the cheapest
// idempotent admin POST. That control and its route were removed on
// 2026-08-25 with the public listener, so this drives the storage purge
// instead -- intercepted before it reaches the server, so nothing is
// actually purged.
import { newBrowser, newContext, adminApiLogin, check, summary, openUserMenu, BASE_URL, ADMIN_USER, adminPassword } from "./_helpers.mjs";

async function loginAsAdminUi(page) {
  await page.goto(BASE_URL);
  await page.waitForSelector('input[placeholder="Username or email"]', { timeout: 15000 });
  await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
  await page.fill('input[type="password"]', adminPassword());
  await page.click('button[type="submit"]');
  await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 15000 });
}

async function main() {
  const browser = await newBrowser();
  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  await loginAsAdminUi(page);

  await openUserMenu(page);
  const adminButton = page.locator('[data-testid="admin-open"]').first();
  check("the admin-console entry is visible for an admin user", (await adminButton.count()) > 0);
  await adminButton.click();
  await page.waitForSelector("text=Admin console", { timeout: 10000 });

  // Intercept the purge call and force a server error. The route never
  // reaches the server, so no data is touched.
  await page.route("**/api/admin/purge/**", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "forced failure for FE-SEC-02" }) }),
  );

  // The deployment-wide purges live in the Danger zone behind a typed
  // phrase now, not behind a first-visible "Purge" button. The request is
  // still answered by the route above with a forced 500, so no purge ever
  // reaches the server even though the button is armed.
  // Prove the interception holds BEFORE arming a button that would purge
  // every user's jobs on a shared deployment: a purge sent from this page
  // must come back as the forced 500, or the spec stops here.
  const probe = await page.evaluate(async () => {
    // PUT, which the server has no route for: if the interception were not
    // in place this probe would get a harmless 405, never a real purge.
    const r = await fetch("/api/admin/purge/jobs", { method: "PUT" });
    return { status: r.status, body: await r.text() };
  });
  if (probe.status !== 500 || !probe.body.includes("forced failure for FE-SEC-02")) {
    console.error(`the purge interception is not in place (${probe.status}); refusing to arm the button`);
    await browser.close();
    process.exit(1);
  }
  await page.locator('[data-testid="admin-nav-danger"]').click();
  await page.waitForSelector('[data-testid="admin-purge-jobs-phrase"]', { timeout: 10000 });
  await page.locator('[data-testid="admin-purge-jobs-phrase"]').fill("PURGE ALL JOBS");
  const toggleButton = page.locator('[data-testid="admin-purge-jobs"]');
  const beforeText = await toggleButton.textContent();
  // Snapshot BEFORE the click so the error check below can look for NEW
  // error-ish content in the delta, not static always-present page text
  // that happens to contain "failed" (e.g. the purge section's own
  // "Every completed/failed/cancelled job..." description) -- a plain
  // whole-page regex test produced exactly that false positive here.
  const bodyBefore = await page.locator("body").innerText();
  await toggleButton.click();
  await page.waitForTimeout(1500);
  const afterText = await toggleButton.textContent();

  const bodyAfter = await page.locator("body").innerText();
  const errorPattern = /error|failed to|forced failure|something went wrong|could not/i;
  const newErrorText = bodyAfter
    .split("\n")
    .filter((line) => errorPattern.test(line) && !bodyBefore.includes(line));
  const anyErrorVisible = newErrorText.length > 0;

  check(
    "the button text is unchanged after the forced 500 (mutation did not silently succeed)",
    beforeText?.trim() === afterText?.trim(),
    `before=${beforeText?.trim()} after=${afterText?.trim()}`,
  );
  check(
    "SOME NEW visible error indication appears after the mutation fails (vs. before the click)",
    anyErrorVisible,
    anyErrorVisible
      ? `unexpected -- new error-ish text appeared: ${JSON.stringify(newErrorText)} -- this finding may be stale`
      : "CONFIRMED: no new error text anywhere -- the button just silently reverted with zero user-visible feedback",
  );

  await browser.close();
  const ok = summary();
  // This script's meaningful outcome is "confirmed the silent-failure gap" --
  // exit 1 on the second check is the expected/interesting result, matching
  // this suite's sec_*/fe_sec_* convention (see tests/README.md).
  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
