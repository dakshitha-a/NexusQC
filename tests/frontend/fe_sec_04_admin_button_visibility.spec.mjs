// FE-SEC-04: confirms the two layers of admin gating agree. Client-side:
// AccountBar (frontend/src/app-shell/ShellLayout.tsx) only renders the
// "Admin" button when user.role === "admin" -- a non-admin should never
// even see it. Server-side (the REAL boundary, per CONF-01 in the backend
// suite): a direct in-page fetch() to an admin route must still 403
// regardless of what's rendered, confirming a non-admin can't bypass the
// UI via DevTools/console to get real admin functionality.
import { newBrowser, newContext, adminApiLogin, mintInvite, deleteUserByUsername, check, summary, BASE_URL } from "./_helpers.mjs";

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");

  const username = "qatest_fe04_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  await page.goto(`${BASE_URL}/?invite=${token}`);
  await page.waitForSelector('input[placeholder="Invite token"]', { timeout: 15000 });
  await page.fill('input[placeholder="Invite token"]', token);
  await page.fill('input[placeholder="Email"]', `${username}@example.test`);
  await page.fill('input[placeholder="Username"]', username);
  await page.fill('input[placeholder="Password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForSelector('button:has-text("Log out")', { timeout: 15000 });

  const adminButtonCount = await page.locator('button:has-text("Admin")').count();
  check("non-admin user does NOT see an 'Admin' button in the UI", adminButtonCount === 0, `found ${adminButtonCount}`);

  const directFetchStatus = await page.evaluate(async () => {
    const res = await fetch("/api/admin/config", { credentials: "same-origin" });
    return res.status;
  });
  check(
    "a direct in-page fetch() to an admin route still 403s for a non-admin, even with no button rendered",
    directFetchStatus === 403,
    `got ${directFetchStatus}`,
  );

  await deleteUserByUsername(adminCtx, username);
  await browser.close();
  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
