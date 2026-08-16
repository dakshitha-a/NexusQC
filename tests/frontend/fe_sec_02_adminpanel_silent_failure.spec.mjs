// FE-SEC-02: AdminPanel.tsx's 5 useMutation calls (patchMutation,
// toggleAccessMutation, purgeJobsMutation, purgeKbMutation,
// purgeThreadsMutation) have no onError/isError handling anywhere
// (confirmed by reading the file in full). Intercepts the
// toggle-public-access POST and makes it fail with a 500, clicks the
// toggle button, and checks whether ANY error text appears anywhere on
// the page -- confirmed-bug if the button just silently reverts to its
// normal (pre-click) state with nothing shown to the user.
import { newBrowser, newContext, adminApiLogin, check, summary, BASE_URL, ADMIN_USER, adminPassword } from "./_helpers.mjs";

async function loginAsAdminUi(page) {
  await page.goto(BASE_URL);
  await page.waitForSelector('input[placeholder="Username or email"]', { timeout: 15000 });
  await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
  await page.fill('input[type="password"]', adminPassword());
  await page.click('button[type="submit"]');
  await page.waitForSelector('button:has-text("Log out")', { timeout: 15000 });
}

async function main() {
  const browser = await newBrowser();
  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  await loginAsAdminUi(page);

  const adminButton = page.locator('button:has-text("Admin")').first();
  check("Admin button is visible for an admin user", (await adminButton.count()) > 0);
  await adminButton.click();
  await page.waitForSelector("text=Admin console", { timeout: 10000 });

  // Intercept the toggle-public-access call and force a server error.
  await page.route("**/api/admin/toggle-public-access", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "forced failure for FE-SEC-02" }) }),
  );

  const toggleButton = page.locator('button:has-text("Enabled -- click to disable"), button:has-text("Disabled -- click to enable")').first();
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
