// P1: the invites section of the admin console -- create, copy the deep
// link, and revoke, all through the real UI rather than the API.
//
// The revoke half is verified twice on purpose: once in the UI (the row
// flips to "revoked") and once against the server (revoked_at is actually
// set). A UI-only assertion would pass on optimistic local state that never
// reached Postgres.
import {
  newBrowser,
  newContext,
  check,
  summary,
  BASE_URL,
  ADMIN_USER,
  adminPassword,
  randSuffix,
} from "./_helpers.mjs";

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

  await page.locator('[data-testid="admin-open"]').click();
  await page.waitForSelector("text=Admin console", { timeout: 10000 });

  const invitesHeading = page.locator('h3:has-text("Invites")');
  check("the admin console has an Invites section", (await invitesHeading.count()) > 0);

  // --- Create ----------------------------------------------------------
  const hint = `qatest-${randSuffix()}@example.test`;
  await page.fill('input[placeholder="Email hint (optional)"]', hint);
  await page.click('button:has-text("Create invite")');

  // The "New invite link" callout carries the freshly minted token.
  await page.waitForSelector("text=New invite link", { timeout: 10000 });
  const linkValue = await page
    .locator('input[readonly]')
    .first()
    .inputValue();
  check(
    "creating an invite surfaces a usable ?invite= deep link",
    linkValue.includes("/?invite="),
    linkValue.slice(0, 60),
  );
  const token = linkValue.split("/?invite=")[1];

  const rowVisible = await page.locator(`text=${hint}`).count();
  check("the new invite appears in the table with its email hint", rowVisible > 0);

  const pendingCells = await page.locator("td", { hasText: /^pending$/ }).count();
  check("the new invite is listed as pending", pendingCells > 0, `${pendingCells} pending row(s)`);

  // --- Revoke ----------------------------------------------------------
  // Scope to the row carrying this run's own email hint so a leftover
  // invite from an earlier run is never the one revoked.
  const row = page.locator("tr", { hasText: hint }).first();
  await row.locator('button:has-text("Revoke")').click();
  await row.locator('button:has-text("Revoke")').last().click(); // the confirm
  await page.waitForTimeout(1500);

  const revokedText = await row.innerText();
  check(
    "the revoked invite's row flips to revoked in the UI",
    /revoked/i.test(revokedText),
    revokedText.replace(/\s+/g, " ").slice(0, 80),
  );

  const serverRow = await page.evaluate(async (t) => {
    const r = await fetch("/api/admin/invites", { credentials: "same-origin" });
    const rows = await r.json();
    return rows.find((x) => x.token === t) ?? null;
  }, token);
  check(
    "the server agrees the invite is revoked (revoked_at set)",
    serverRow && serverRow.revoked_at !== null,
    JSON.stringify(serverRow && serverRow.revoked_at),
  );

  // The point of revoking: it must actually stop registration.
  const registerStatus = await page.evaluate(async (t) => {
    const r = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "omit",
      body: JSON.stringify({
        invite_token: t,
        email: `qatest-revoked-${Date.now()}@example.test`,
        username: `qatest_revoked_${Date.now().toString().slice(-8)}`,
        password: "correct horse battery staple 1",
      }),
    });
    return r.status;
  }, token);
  check(
    "a revoked invite cannot register an account",
    registerStatus === 400,
    `got ${registerStatus}`,
  );

  await browser.close();
  process.exit(summary() ? 0 : 1);
}

main();
