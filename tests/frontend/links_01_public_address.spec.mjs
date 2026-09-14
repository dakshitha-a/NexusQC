// LINKS-01: the links the console hands out are built on the deployment's
// public address, set in the Deployment section, and fall back to the page's
// own origin when nothing is set.
//
// The situation this exists for: a host shared over Tailscale with each user
// is reached by every recipient at a different address, so an invite link
// carrying the admin's own address was dead for all of them. Driven through
// the real console: set the address in the Deployment section, mint an
// invite and issue a reset for a throwaway user, read both link inputs; then
// clear it and read them again. Nothing is navigated to; the addresses here
// are invented. The previous setting is restored and the throwaway user
// deleted whether or not the checks pass.
import { newBrowser, newContext, adminApiLogin, mintInvite, deleteUserByUsername, check, summary, LOGGED_IN, BASE_URL, openUserMenu, randSuffix } from "./_helpers.mjs";

const PUBLIC = "https://example-host.test:8444";
let ctx = null;
let browser = null;
let prior = null;
let username = null;

async function openDeployment(page) {
  await openUserMenu(page);
  await page.click('[data-testid="admin-open"]');
  await page.waitForSelector("text=Admin console", { timeout: 10000 });
  await page.waitForSelector('[data-testid="admin-nav-deployment"]', { timeout: 10000 });
  await page.waitForTimeout(800);
  await page.click('[data-testid="admin-nav-deployment"]');
  await page.waitForSelector('[data-testid="public-url-input"]', { timeout: 10000 });
}

async function readInviteLink(page) {
  await page.click('[data-testid="admin-nav-invites"]');
  await page.waitForTimeout(600);
  await page.fill('input[placeholder="Email hint (optional)"]', `qatest-${randSuffix()}@example.test`);
  await page.click('button:has-text("Create invite")');
  await page.waitForSelector("text=New invite link", { timeout: 10000 });
  return page.locator("input[readonly]").first().inputValue();
}

async function readResetLink(page) {
  await page.click('[data-testid="admin-nav-users"]');
  await page.waitForTimeout(600);
  const row = page.locator(`[data-testid="admin-user-row-${username}"]`);
  await row.click();
  await page.waitForSelector(`[data-testid="reset-password-${username}"]`, { timeout: 10000 });
  await page.locator(`[data-testid="reset-password-${username}"]`).click();
  await page.waitForSelector('[data-testid="reset-link-value"]', { timeout: 10000 });
  return page.locator('[data-testid="reset-link-value"]').inputValue();
}

async function main() {
  browser = await newBrowser();
  ctx = await newContext(browser);
  await adminApiLogin(ctx);

  // Remember what the deployment had, to put it back.
  prior = await (await ctx.request.get(`${BASE_URL}/api/admin/config`)).json();

  // A throwaway user to issue a reset for.
  const token = await mintInvite(ctx, "user");
  username = "qatest_links_" + randSuffix(6);
  // In its own context: registering logs the new user in on whichever
  // cookie jar made the call, and this one is the admin's.
  const userCtx = await newContext(browser);
  const reg = await userCtx.request.post(`${BASE_URL}/api/auth/register`, {
    data: { invite_token: token, email: `${username}@example.test`, username, password: "correct horse battery staple 1", first_name: "QA", last_name: "Tester" },
    headers: { Origin: BASE_URL },
  });
  check("the throwaway user registers", reg.ok(), `${reg.status()}`);
  await userCtx.close();

  const page = await ctx.newPage();
  await page.goto(BASE_URL);
  await page.waitForSelector(LOGGED_IN, { timeout: 15000 });

  // --- Set the public address through the console --------------------------
  await openDeployment(page);
  const sourceBefore = await page.locator('[data-testid="public-url-source"]').textContent();
  check("the Deployment section shows the public address and where it comes from", /In effect:/.test(sourceBefore), sourceBefore.trim());

  await page.fill('[data-testid="public-url-input"]', "https://x/path");
  await page.click('[data-testid="public-url-save"]');
  await page.waitForSelector('[data-testid="public-url-error"]', { timeout: 10000 });
  const err = await page.locator('[data-testid="public-url-error"]').textContent();
  check("a value with a path is refused, with the server's rule shown inline", /origin/.test(err), err.trim());

  await page.fill('[data-testid="public-url-input"]', PUBLIC);
  await page.click('[data-testid="public-url-save"]');
  await page.waitForFunction((v) => document.querySelector('[data-testid="public-url-source"]')?.textContent.includes(v), PUBLIC, { timeout: 10000 });
  const sourceSet = await page.locator('[data-testid="public-url-source"]').textContent();
  check("after saving, the section says the address is in effect and set here", sourceSet.includes(PUBLIC) && /set here/.test(sourceSet), sourceSet.trim());
  await page.screenshot({ path: "/tmp/links_01_deployment.png" });

  // --- Links are built on it ------------------------------------------------
  const invite = await readInviteLink(page);
  check("a new invite link starts with the public address, not this page's origin",
    invite.startsWith(`${PUBLIC}/?invite=`) && !invite.startsWith(BASE_URL), invite.slice(0, 70));
  const reset = await readResetLink(page);
  check("a reset link starts with the public address too",
    reset.startsWith(`${PUBLIC}/?reset=`), reset.slice(0, 70));
  await page.screenshot({ path: "/tmp/links_01_reset.png" });

  // --- Clear it: links fall back to the page's own origin ---------------------
  await page.click('[data-testid="admin-nav-deployment"]');
  await page.waitForSelector('[data-testid="public-url-clear"]', { timeout: 10000 });
  await page.click('[data-testid="public-url-clear"]');
  await page.waitForFunction((v) => !document.querySelector('[data-testid="public-url-source"]')?.textContent.includes(v), PUBLIC, { timeout: 10000 });
  const invite2 = await readInviteLink(page);
  const expectedFallback = prior.public_url_source === "env" ? prior.public_url : BASE_URL;
  check("with the console value cleared, links fall back to .env or this page's origin",
    invite2.startsWith(`${expectedFallback}/?invite=`), `${invite2.slice(0, 70)} (expected base ${expectedFallback})`);
}

main()
  .catch((e) => { console.error(e); })
  .finally(async () => {
    try {
      if (ctx) {
        if (prior) {
          const restore = prior.public_url_source === "setting" ? prior.public_url : "";
          await ctx.request.patch(`${BASE_URL}/api/admin/config`, { data: { key: "public_url", value: restore }, headers: { Origin: BASE_URL } });
          const now = await (await ctx.request.get(`${BASE_URL}/api/admin/config`)).json();
          check("the deployment's own setting is restored", now.public_url === prior.public_url && now.public_url_source === prior.public_url_source, `${now.public_url} (${now.public_url_source})`);
        }
        if (username) await deleteUserByUsername(ctx, username);
      }
      if (browser) await browser.close();
    } finally {
      const ok = summary();
      process.exit(ok ? 0 : 1);
    }
  });
