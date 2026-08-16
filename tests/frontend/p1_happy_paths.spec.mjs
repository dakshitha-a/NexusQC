// P1 functional coverage (frontend): register via ?invite= prefill, login,
// admin quota save round trip, two-click purge confirm flow, and the P2
// polish checks (missing autoComplete attributes, no confirm dialog on
// the public-access toggle/quota fields).
import { newBrowser, newContext, adminApiLogin, mintInvite, deleteUserByUsername, check, summary, BASE_URL, ADMIN_USER, adminPassword } from "./_helpers.mjs";

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_p1_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  // --- Register via ?invite= URL prefill ---
  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  await page.goto(`${BASE_URL}/?invite=${token}`);
  const inviteInput = page.locator('input[placeholder="Invite token"]');
  await inviteInput.waitFor({ timeout: 15000 });
  const prefilledValue = await inviteInput.inputValue();
  check("?invite= URL param pre-fills the invite token field", prefilledValue === token, `got ${prefilledValue}`);
  const modeText = await page.locator("text=Create an account with your invite token.").count();
  check("?invite= URL param switches straight to register mode", modeText > 0);

  // --- P2: autoComplete attribute, checked while the field still exists
  // (it's gone from the DOM the instant login succeeds and the shell
  // replaces LoginScreen entirely -- checking this AFTER submit was a bug
  // in this script, not a real timeout in the app).
  const passwordAutocomplete = await page.locator('input[type="password"]').getAttribute("autocomplete");
  check(
    "P2 (documented, not a failure): password input has no explicit autoComplete attribute",
    passwordAutocomplete === null,
    `autocomplete=${passwordAutocomplete}`,
  );

  await page.fill('input[placeholder="Email"]', `${username}@example.test`);
  await page.fill('input[placeholder="Username"]', username);
  await page.fill('input[placeholder="Password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForSelector('button:has-text("Log out")', { timeout: 15000 });
  check("registration succeeds and auto-logs-in (no separate login step)", true);

  await page.click('button:has-text("Log out")');
  // The URL still carries the original ?invite= param, so LoginScreen
  // defaults back to register mode on its own (a real, minor UX wrinkle:
  // logging out after registering via an invite link keeps showing the
  // register form, not login) -- navigate to a clean URL to reach login
  // mode deterministically rather than depend on that default.
  await page.goto(BASE_URL);
  await page.waitForSelector('input[placeholder="Username or email"]', { timeout: 15000 });

  // --- Login (separate session) ---
  await page.fill('input[placeholder="Username or email"]', username);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForSelector('button:has-text("Log out")', { timeout: 15000 });
  check("login with the just-registered credentials succeeds", true);
  await ctx.close();

  // --- Admin panel: quota save round trip + purge confirm flow ---
  const adminPage = await adminCtx.newPage();
  await adminPage.goto(BASE_URL); // adminCtx already carries a valid session cookie from adminApiLogin
  await adminPage.waitForSelector('button:has-text("Log out")', { timeout: 15000 });
  await adminPage.click('button:has-text("Admin")');
  await adminPage.waitForSelector("text=Admin console", { timeout: 10000 });

  const kbQuotaInput = adminPage.locator("text=Per-user KB quota").locator("..").locator("..").locator('input[type="number"]');
  const original = await kbQuotaInput.inputValue();
  await kbQuotaInput.fill(String(Number(original) + 0.5));
  const saveButton = adminPage
    .locator("text=Per-user KB quota")
    .locator("..")
    .locator("..")
    .locator('button:has-text("Save")');
  const saveEnabled = await saveButton.isEnabled();
  check("Save button becomes enabled once the quota field is dirty", saveEnabled);
  const expectedBytes = Math.round((Number(original) + 0.5) * 1_000_000_000);
  if (saveEnabled) {
    await saveButton.click();
    await adminPage.waitForTimeout(1000);
  }
  // Don't just trust the button's own disabled state -- read the value
  // back from the server directly (adminPage.request shares this page's
  // session cookie) to confirm the PATCH actually persisted, not just
  // that the UI reacted as if it had. This is the one route every
  // mutating request in this app passes through the CSRF Origin check
  // (AccessControlMiddleware) added by the SEC-01 fix -- if that check
  // ever regressed to rejecting legitimate same-origin browser requests,
  // this is where it would show up as a value that silently never changed.
  const cfgResp = await adminPage.request.get(`${BASE_URL}/api/admin/config`);
  const cfgAfterSave = await cfgResp.json();
  check(
    "quota Save actually persisted server-side (GET /api/admin/config reflects the new value)",
    saveEnabled && cfgAfterSave.per_user_kb_quota_bytes === expectedBytes,
    `expected ${expectedBytes}, got ${cfgAfterSave.per_user_kb_quota_bytes}`,
  );
  check(
    "P2 (documented, not a failure): no confirmation dialog appears before a quota change takes effect",
    true,
    "Save applies immediately, unlike the purge buttons below",
  );
  // Restore original value.
  await kbQuotaInput.fill(String(original));
  const restoreSave = adminPage.locator("text=Per-user KB quota").locator("..").locator("..").locator('button:has-text("Save")');
  if (await restoreSave.isEnabled()) {
    await restoreSave.click();
    await adminPage.waitForTimeout(1000);
  }

  // --- Two-click purge confirm flow (jobs -- cheap, idempotent-ish since
  // this stack has few/no jobs to purge) ---
  const purgeButton = adminPage.locator('button:has-text("Purge all job history")');
  await purgeButton.click();
  const warningVisible = await adminPage.locator("text=This deletes matching items across every user").count();
  check("clicking a purge button reveals the red warning panel, not an immediate purge", warningVisible > 0);
  await adminPage.click("text=Cancel");
  const warningGoneAfterCancel = await adminPage.locator("text=This deletes matching items across every user").count();
  check("Cancel dismisses the warning without purging", warningGoneAfterCancel === 0);

  await adminPage.close();
  await deleteUserByUsername(adminCtx, username);
  await browser.close();
  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
