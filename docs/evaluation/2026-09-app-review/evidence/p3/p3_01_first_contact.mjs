// P3.1: first contact. The login screen, wrong-password handling, the
// welcome message, the help flyout, appearance, the account menu, change
// password, logout and return. Run with the stack quiet:
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_01_first_contact.mjs
//
// Uses qa_review_3, the throwaway account, for the password change, so the
// other two keep their known credentials.
import { start, loginAs, Log, BASE_URL, newContext, accounts, inventoryOf, check, summary } from "./_p3.mjs";

const L = new Log("p3_01_first_contact");
const browser = await start();

// ---- The login screen, cold, as an anonymous visitor ----------------------
{
  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  page.__console = [];
  page.on("console", (m) => { if (m.type() === "error") page.__console.push(m.text().slice(0, 200)); });

  await L.observe(page, "login-screen-cold", async () => {
    const t = Date.now();
    await page.goto(`${BASE_URL}/`);
    await page.waitForSelector('input[placeholder="Username or email"]', { timeout: 30000 });
    return { first_paint_ms: Date.now() - t, console: page.__console };
  });

  // What does the screen tell a stranger about what this is?
  await L.observe(page, "login-screen-text", async () => {
    const blurb = await page.locator('[data-testid="auth-blurb"]').textContent().catch(() => null);
    const hasForgot = await page.locator('[data-testid="forgot-password"]').count();
    return { blurb: blurb && blurb.trim().slice(0, 300), forgot_password_link: hasForgot > 0 };
  });

  // Wrong password: what does it say, how long does it take, is it the same
  // message as an unknown user (it should be, per the timing-oracle fix)?
  await L.observe(page, "wrong-password", async () => {
    await page.fill('input[placeholder="Username or email"]', "qa_review");
    await page.fill('input[placeholder="Password"]', "definitely not the password");
    const t = Date.now();
    await page.click('[data-testid="auth-submit"]');
    await page.waitForSelector('[data-testid="auth-error"]', { timeout: 15000 });
    const msg = (await page.locator('[data-testid="auth-error"]').textContent()).trim();
    return { ms: Date.now() - t, message: msg };
  });
  await L.observe(page, "unknown-user", async () => {
    await page.fill('input[placeholder="Username or email"]', "nobody_here_" + Date.now());
    await page.fill('input[placeholder="Password"]', "whatever");
    const t = Date.now();
    await page.click('[data-testid="auth-submit"]');
    await page.waitForTimeout(300);
    const msg = (await page.locator('[data-testid="auth-error"]').textContent().catch(() => "")).trim();
    return { ms: Date.now() - t, message: msg };
  });

  // Rate limit: hammer wrong passwords until a 429 shows, count how many it took,
  // and record what the user is told.
  await L.observe(page, "rate-limit-message", async () => {
    let n = 0, msg = "";
    for (n = 1; n <= 25; n++) {
      await page.fill('input[placeholder="Password"]', "wrong " + n);
      await page.click('[data-testid="auth-submit"]');
      await page.waitForTimeout(250);
      msg = (await page.locator('[data-testid="auth-error"]').textContent().catch(() => "")).trim();
      if (/too many|rate|slow down|try again|wait/i.test(msg)) break;
    }
    return { attempts_until_limited: n, message: msg };
  }, { inventory: false });
  await ctx.close();
}

// The rate limiter is keyed on the client IP and the whole review shares one,
// so clear it before logging in for real, the way every backend script does.
import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
// The compose stack lives at the checkout root, five levels up from here.
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../..");
execSync(`docker compose exec -T api python -c "from app.auth.redis_session import get_client; c=get_client(); k=c.keys('qc_agent:ratelimit:*'); c.delete(*k) if k else None"`, { cwd: REPO, stdio: "ignore" });
L.note("rate-limit buckets reset before the real login (shared client IP)");

// ---- A real first login ----------------------------------------------------
const { ctx, page } = await loginAs(browser, "qa_review");

await L.observe(page, "after-login-shell", async () => {
  await page.waitForTimeout(1500);
  return { console: page.__console.slice(0, 10), api_requests_so_far: page.__requests.length };
});

// The welcome message is the app describing itself to a new user.
await L.observe(page, "welcome-message", async () => {
  const body = await page.locator("main").innerText().catch(() => "");
  const toggle = await page.locator('[data-testid="welcome-toggle-details"]').count();
  const tutorial = await page.locator('[data-testid="welcome-open-tutorial"]').count();
  return { has_details_toggle: toggle > 0, has_tutorial_button: tutorial > 0, welcome_excerpt: body.slice(0, 1200) };
});
await L.observe(page, "welcome-details-expanded", async () => {
  const t = page.locator('[data-testid="welcome-toggle-details"]');
  if (await t.count()) await t.click();
  await page.waitForTimeout(400);
  return { text: (await page.locator("main").innerText()).slice(0, 4000) };
});

// The help flyout.
await L.observe(page, "help-flyout", async () => {
  const h = page.locator('[data-testid="rail-help"], [data-testid="rail-help-collapsed"]').first();
  await h.click();
  await page.waitForTimeout(500);
  const text = await page.evaluate(() => document.body.innerText);
  return { chars: text.length, excerpt: text.slice(0, 3000) };
});
await page.keyboard.press("Escape");

// Appearance: light, dark, system. Capture the body background each time.
async function bg() { return page.evaluate(() => getComputedStyle(document.body).backgroundColor); }
await L.observe(page, "appearance-open", async () => {
  await page.locator('[data-testid="user-menu-open"]').click();
  await page.waitForTimeout(300);
  const items = await page.locator('[data-testid="user-menu"]').innerText().catch(() => "");
  return { menu_items: items };
});
await L.observe(page, "appearance-flyout", async () => {
  const item = page.locator('[data-testid="user-menu"] >> text=/appearance/i').first();
  if (await item.count()) await item.click();
  await page.waitForTimeout(500);
  return { bg_before: await bg(), text: (await page.evaluate(() => document.body.innerText)).slice(-1500) };
});
for (const mode of ["Dark", "Light", "System"]) {
  await L.observe(page, `appearance-${mode.toLowerCase()}`, async () => {
    const b = page.locator(`button:has-text("${mode}"), [role=radio]:has-text("${mode}"), label:has-text("${mode}")`).first();
    if (await b.count()) await b.click();
    await page.waitForTimeout(400);
    return { bg: await bg(), data_theme: await page.evaluate(() => document.documentElement.getAttribute("data-theme")) };
  });
}
await page.keyboard.press("Escape");

// The account flyout and change password, on the throwaway account.
await ctx.close();
{
  const { ctx: c3, page: p3, acct } = await loginAs(browser, "qa_review_3");
  await L.observe(p3, "account-flyout", async () => {
    await p3.locator('[data-testid="user-menu-open"]').click();
    await p3.waitForTimeout(300);
    const acc = p3.locator('[data-testid="account-open"]');
    if (await acc.count()) await acc.click();
    await p3.waitForTimeout(500);
    return { text: (await p3.evaluate(() => document.body.innerText)).slice(-2000) };
  });
  const newPw = "changed review pass phrase 2026";
  await L.observe(p3, "change-password", async () => {
    const pws = p3.locator('input[type="password"]');
    const n = await pws.count();
    if (n >= 2) {
      await pws.nth(0).fill(acct.password);
      await pws.nth(1).fill(newPw);
      if (n >= 3) await pws.nth(2).fill(newPw);
    }
    const t = Date.now();
    const btn = p3.locator('[data-testid="change-password-submit"]');
    if (await btn.count()) await btn.click();
    await p3.waitForSelector('[data-testid="change-password-done"], [data-testid="change-password-error"]', { timeout: 15000 }).catch(() => {});
    const done = await p3.locator('[data-testid="change-password-done"]').textContent().catch(() => null);
    const err = await p3.locator('[data-testid="change-password-error"]').textContent().catch(() => null);
    return { ms: Date.now() - t, password_fields: n, done: done && done.trim(), error: err && err.trim() };
  });
  // Logout, then log back in with the NEW password.
  await L.observe(p3, "logout", async () => {
    await p3.keyboard.press("Escape");
    await p3.locator('[data-testid="user-menu-open"]').click();
    await p3.waitForTimeout(300);
    await p3.locator('[data-testid="shell-logout"]').click();
    await p3.waitForSelector('input[placeholder="Username or email"]', { timeout: 15000 });
    return { back_at_login: true };
  });
  await L.observe(p3, "login-with-new-password", async () => {
    await p3.fill('input[placeholder="Username or email"]', acct.username);
    await p3.fill('input[placeholder="Password"]', newPw);
    await p3.click('[data-testid="auth-submit"]');
    const ok = await p3.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 }).then(() => true).catch(() => false);
    const err = await p3.locator('[data-testid="auth-error"]').textContent().catch(() => null);
    return { logged_in: ok, error: err && err.trim() };
  });
  L.note(`qa_review_3 password is now: ${newPw}`);
  // Persist the new password so later steps can use the account.
  const accts = accounts(); accts.qa_review_3.password = newPw;
  const fs = await import("node:fs"); fs.writeFileSync(process.env.QC_REVIEW_ACCOUNTS, JSON.stringify(accts, null, 2));
  await L.observe(p3, "return-after-logout-state", async () => {
    return { console: p3.__console.slice(0, 10) };
  });
  await c3.close();
}

await browser.close();
console.log(`\nevidence: ${L.file}\nscreenshots: ${L.shotDir}/`);
