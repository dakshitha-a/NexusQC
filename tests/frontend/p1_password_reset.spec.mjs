// P1: the admin-issued password reset, driven entirely through the real UI.
//
// The whole feature is two screens that have to agree on one deep link: an
// admin issues a reset in the console and gets a /?reset=<token> URL, and the
// person opens that URL and is put in front of a reset form rather than the
// sign-in one. A backend test can prove the token works; only a browser can
// prove the link the console hands out is a link this app actually parses.
//
// Every assertion below therefore checks something rendered. The reset form
// is asserted VISIBLE before it is filled -- a spec that only submitted the
// form and checked the API would pass even if nothing had drawn on screen.
import {
  newBrowser,
  newContext,
  check,
  summary,
  openUserMenu,
  BASE_URL,
  ADMIN_USER,
  adminPassword,
  randSuffix,
  adminApiLogin,
  mintInvite,
  deleteUser,
} from "./_helpers.mjs";

const NEW_PASSWORD = "a brand new password 12";

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
  const adminCtx = await newContext(browser);
  const apiCtx = await newContext(browser);
  await adminApiLogin(apiCtx);

  // Somebody to lose their password.
  const username = `qatest_${randSuffix()}`;
  const token = await mintInvite(apiCtx, "user");
  const regPage = await apiCtx.newPage();
  // Origin matters: the backend rejects a cross-origin-looking POST, and
  // without this header registration fails silently and the first thing you
  // see is a missing row in the admin console thirty lines further down.
  const reg = await regPage.request.post(`${BASE_URL}/api/auth/register`, {
    data: {
      invite_token: token,
      email: `${username}@example.test`,
      username,
      password: "correct horse battery staple 1",
      first_name: "QA",
      last_name: "Tester",
    },
    headers: { Origin: BASE_URL },
  });
  if (!reg.ok()) throw new Error(`could not create the test account: ${reg.status()} ${await reg.text()}`);
  const victim = await reg.json();
  await regPage.close();

  // --- The login screen offers a way in ---------------------------------
  const anonPage = await (await newContext(browser)).newPage();
  await anonPage.goto(BASE_URL);
  await anonPage.waitForSelector('[data-testid="forgot-password"]', { timeout: 15000 });
  check("the sign-in screen offers a 'Forgot your password?' link", true);
  await anonPage.locator('[data-testid="forgot-password"]').click();
  await anonPage.waitForSelector('[data-testid="auth-form-reset"]', { timeout: 5000 });
  check(
    "clicking it renders the reset form, with a token field",
    await anonPage.locator('[data-testid="reset-token"]').isVisible(),
  );
  check(
    "and says where a token comes from, since nothing is emailed here",
    (await anonPage.locator("text=issued by an administrator").count()) > 0,
  );

  // --- An admin issues one ------------------------------------------------
  const page = await adminCtx.newPage();
  await loginAsAdminUi(page);
  await openUserMenu(page);
  await page.locator('[data-testid="admin-open"]').click();
  await page.waitForSelector("text=Admin console", { timeout: 10000 });
  await page.locator('[data-testid="admin-nav-users"]').click();
  await page.waitForTimeout(600);

  const row = page.locator(`[data-testid="admin-user-row-${username}"]`);
  check("the new account is listed in the admin console", (await row.count()) > 0);
  await row.click();
  await page.waitForSelector(`[data-testid="reset-password-${username}"]`, { timeout: 10000 });
  check(
    "the expanded row shows an 'Issue password reset' action",
    await page.locator(`[data-testid="reset-password-${username}"]`).isVisible(),
  );

  await page.locator(`[data-testid="reset-password-${username}"]`).click();
  await page.waitForSelector('[data-testid="reset-link-panel"]', { timeout: 10000 });
  check(
    "issuing one renders the link panel",
    await page.locator('[data-testid="reset-link-panel"]').isVisible(),
  );
  const link = await page.locator('[data-testid="reset-link-value"]').inputValue();
  check("the panel carries a usable ?reset= deep link", link.includes("/?reset="), link.slice(0, 60));

  // --- The person uses it -------------------------------------------------
  const victimCtx = await newContext(browser);
  const victimPage = await victimCtx.newPage();
  await victimPage.goto(link);
  await victimPage.waitForSelector('[data-testid="auth-form-reset"]', { timeout: 15000 });
  check(
    "opening the link lands on the reset form, not the sign-in form",
    await victimPage.locator('[data-testid="auth-form-reset"]').isVisible(),
  );
  const prefilled = await victimPage.locator('[data-testid="reset-token"]').inputValue();
  check("the token is prefilled from the URL", prefilled.length > 0 && link.includes(prefilled));

  // The confirm field is browser-only, so this mismatch can only be caught here.
  await victimPage.fill('[data-testid="reset-password"]', NEW_PASSWORD);
  await victimPage.fill('[data-testid="reset-confirm"]', "something else entirely");
  await victimPage.click('[data-testid="auth-submit"]');
  await victimPage.waitForSelector('[data-testid="auth-error"]', { timeout: 5000 });
  check(
    "two different passwords are refused in the browser, before the token is spent",
    (await victimPage.locator('[data-testid="auth-error"]').innerText()).includes("do not match"),
  );

  await victimPage.fill('[data-testid="reset-confirm"]', NEW_PASSWORD);
  await victimPage.click('[data-testid="auth-submit"]');
  await victimPage.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });
  check("setting the password signs them straight in", true);

  const me = await (await victimPage.request.get(`${BASE_URL}/api/auth/me`)).json();
  check("and they are signed in as themselves", me.username === username, JSON.stringify(me));

  // The link is single-use: a second visit must not work.
  const replayPage = await (await newContext(browser)).newPage();
  await replayPage.goto(link);
  await replayPage.waitForSelector('[data-testid="auth-form-reset"]', { timeout: 15000 });
  await replayPage.fill('[data-testid="reset-password"]', "yet another one 13");
  await replayPage.fill('[data-testid="reset-confirm"]', "yet another one 13");
  await replayPage.click('[data-testid="auth-submit"]');
  await replayPage.waitForSelector('[data-testid="auth-error"]', { timeout: 10000 });
  check(
    "reusing a spent link is refused, with the error shown on screen",
    (await replayPage.locator('[data-testid="auth-error"]').count()) > 0,
  );

  await deleteUser(apiCtx, victim.id);
  await browser.close();
  summary();
}

main();
