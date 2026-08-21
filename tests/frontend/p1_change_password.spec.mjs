// P1: the account flyout's change-password form.
//
// The check this file exists for is the wrong-password one. While
// /api/auth/change-password returned 401 for a bad current password,
// lib/api.ts's global auth-error handler treated that as a dead session and
// bounced the user to the login screen -- so mistyping your own password
// logged you out. Asserting "still logged in after a rejected attempt" is
// the regression guard; asserting the error text alone would not catch it,
// because the error briefly renders either way.
import {
  newBrowser,
  newContext,
  adminApiLogin,
  mintInvite,
  deleteUserByUsername,
  check,
  summary,
  openUserMenu,
  BASE_URL,
  randSuffix,
} from "./_helpers.mjs";

const PASSWORD = "correct horse battery staple 1";
const NEW_PASSWORD = "a different correct horse 2";

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx);

  const username = `qatest_pw_${randSuffix(6)}`;
  const ctx = await newContext(browser);
  const page = await ctx.newPage();

  await page.goto(`${BASE_URL}/?invite=${token}`);
  await page.waitForSelector('input[placeholder="Invite token"]', { timeout: 15000 });
  await page.fill('input[placeholder="Invite token"]', token);
  await page.fill('input[placeholder="Email"]', `${username}@example.test`);
  await page.fill('input[placeholder="Username"]', username);
  await page.fill('input[placeholder="First name"]', "QA");
  await page.fill('input[placeholder="Last name"]', "Tester");
  await page.fill('input[placeholder="Password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });

  // A non-admin must still get the account panel -- this is the whole
  // "available to all users" requirement. Both entries live in the cogwheel
  // menu, so it has to be open before either count means anything.
  await openUserMenu(page);
  const accountButton = page.locator('[data-testid="account-open"]');
  check("a non-admin user has an Account entry", (await accountButton.count()) > 0);
  check(
    "a non-admin user still has NO admin-console entry",
    (await page.locator('[data-testid="admin-open"]').count()) === 0,
  );

  await accountButton.click();
  await page.waitForSelector('[data-testid="change-password-submit"]', { timeout: 10000 });

  // --- Wrong current password ------------------------------------------
  const inputs = page.locator('input[type="password"]');
  await inputs.nth(0).fill("definitely-not-the-password");
  await inputs.nth(1).fill(NEW_PASSWORD);
  await inputs.nth(2).fill(NEW_PASSWORD);
  await page.locator('[data-testid="change-password-submit"]').click();

  await page.waitForSelector('[data-testid="change-password-error"]', { timeout: 10000 });
  check("a wrong current password shows an inline error", true);

  // The regression guard.
  await page.waitForTimeout(1500);
  const stillIn = await page.locator('[data-testid="user-menu-open"]').count();
  check(
    "the user is STILL LOGGED IN after a rejected password attempt",
    stillIn > 0,
    stillIn > 0 ? "" : "bounced to the login screen -- the 401 auth-handler trap is back",
  );

  // --- Correct current password ----------------------------------------
  await inputs.nth(0).fill(PASSWORD);
  await inputs.nth(1).fill(NEW_PASSWORD);
  await inputs.nth(2).fill(NEW_PASSWORD);
  await page.locator('[data-testid="change-password-submit"]').click();

  await page.waitForSelector('[data-testid="change-password-done"]', { timeout: 15000 });
  check("a correct current password reports success", true);

  const stillInAfter = await page.locator('[data-testid="user-menu-open"]').count();
  check("the user stays signed in on this device after changing it", stillInAfter > 0);

  await deleteUserByUsername(adminCtx, username);
  await browser.close();
  process.exit(summary() ? 0 : 1);
}

main();
