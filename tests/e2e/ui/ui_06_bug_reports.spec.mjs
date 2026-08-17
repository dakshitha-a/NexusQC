// Bug reports end to end: a normal user files one with a screenshot, an
// admin reads it, archives it, unarchives it and deletes it, and a non-admin
// cannot fetch the attachment.
//
// The access-control check here is not incidental. Bug-report attachments
// have no row in ownership_index and never will, and a resource with no
// ownership row is readable by EVERYONE under check_owner_or_admin, not by
// no-one -- which is why the serving route uses require_admin explicitly. A
// regression that routed it through the generic helper would look completely
// fine until this check runs.
import {
  newBrowser, freshContext, uiRegister, check, summary, shot, openUserMenu,
  randSuffix, BASE_URL, LOGGED_IN,
} from "./_ui.mjs";
import { newContext, adminApiLogin, mintInvite, deleteUserByUsername } from "../../frontend/_helpers.mjs";

// Smallest valid PNG: 1x1, so the magic-byte sniff passes on real bytes
// rather than on a declared content-type the client could have made up.
const PNG_B64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

const browser = await newBrowser();
const adminCtx = await newContext(browser);
await adminApiLogin(adminCtx);
const token = await mintInvite(adminCtx, "user");
const username = `qatest_bug_${randSuffix()}`;
const password = "correct horse battery staple 1";

// ------------------------------------------------ file a report as a user
const userCtx = await freshContext(browser);
const page = await userCtx.newPage();
await uiRegister(page, token, username, `${username}@example.test`, password);

await openUserMenu(page);
await page.click('[data-testid="account-open"]');
await page.waitForSelector('[data-testid="bug-report-body"]', { timeout: 15000 });

const BODY = `automated check ${randSuffix()} -- the viewer control overlay`;
await page.fill('[data-testid="bug-report-body"]', BODY);

// Attach through the real file input, with real PNG bytes.
await page.setInputFiles('[data-testid="bug-report-files"]', {
  name: "screenshot.png",
  mimeType: "image/png",
  buffer: Buffer.from(PNG_B64, "base64"),
});
await page.waitForTimeout(500);
const thumbs = await page.locator('[data-testid="bug-report-thumbs"] img').count();
check("the attached screenshot shows as a thumbnail before sending", thumbs === 1, `${thumbs}`);
await shot(page, "ui06-bug-report-form");

await page.click('[data-testid="bug-report-submit"]');
await page.waitForSelector("text=your report was sent", { timeout: 20000 });
check("the report submits with its attachment", true);

// A non-image must be refused client-side, before any upload happens.
await page.fill('[data-testid="bug-report-body"]', "second report, bad attachment");
await page.setInputFiles('[data-testid="bug-report-files"]', {
  name: "notes.txt",
  mimeType: "text/plain",
  buffer: Buffer.from("this is not an image"),
});
await page.waitForTimeout(400);
check("a non-image attachment is refused",
  (await page.locator("text=Only images can be attached").count()) > 0);

// ------------------------------------------------ admin reads it
// adminCtx already carries a session cookie from adminApiLogin, so this lands
// straight on the shell -- driving the login form here would hang waiting for
// a form that is never rendered.
const adminPage = await adminCtx.newPage();
await adminPage.goto(`${BASE_URL}/`);
await adminPage.waitForSelector(LOGGED_IN, { timeout: 30000 });
await openUserMenu(adminPage);
await adminPage.click('[data-testid="admin-open"]');
await adminPage.waitForSelector("text=Admin console", { timeout: 15000 });
await adminPage.locator('[data-testid="admin-nav-reports"]').click();
await adminPage.waitForTimeout(1200);

const reportRow = adminPage.locator("tr", { hasText: BODY.slice(0, 40) }).first();
check("the new report appears in the admin inbox", (await reportRow.count()) > 0);

// The reporter's username must be shown -- the query behind this used to have
// no join to users at all, so it could not be.
const rowText = await reportRow.innerText();
check("the report row names its reporter", rowText.includes(username), rowText.slice(0, 100));

await reportRow.click();
await adminPage.waitForTimeout(700);
const fullBody = await adminPage.locator('[data-testid="admin-report-body"]').first().innerText();
check("expanding the row shows the full report text", fullBody.includes(BODY));

const shotImg = adminPage.locator('[data-testid="admin-report-attachment"]').first();
check("the screenshot is shown to the admin", (await shotImg.count()) > 0);
// A broken <img> still exists in the DOM, so check it actually decoded.
const decoded = await shotImg.evaluate((img) => img.complete && img.naturalWidth > 0).catch(() => false);
check("the screenshot actually loads (not a broken image)", decoded === true);
await shot(adminPage, "ui06-admin-report-expanded");

// ------------------------------------------------ archive round trip
const reportId = await adminPage.evaluate(async (body) => {
  const r = await fetch("/api/admin/bug-reports", { credentials: "same-origin" });
  const rows = await r.json();
  return (rows.find((x) => x.body.includes(body)) ?? {}).id ?? null;
}, BODY.slice(0, 40));
check("the report is retrievable by id from the API", reportId !== null);

await adminPage.locator('[data-testid="admin-report-archive"]').first().click();
await adminPage.waitForTimeout(1500);
const goneFromDefault = await adminPage.locator("tr", { hasText: BODY.slice(0, 40) }).count();
check("archiving removes the report from the default list", goneFromDefault === 0);

await adminPage.locator('[data-testid="admin-reports-show-archived"]').check();
await adminPage.waitForTimeout(800);
const backWithToggle = await adminPage.locator("tr", { hasText: BODY.slice(0, 40) }).count();
check("'Include archived' brings it back", backWithToggle > 0);

// Archiving must not have changed open/closed -- they are independent, and
// the PATCH sends only `archived`.
const afterArchive = await adminPage.evaluate(async (id) => {
  const r = await fetch("/api/admin/bug-reports", { credentials: "same-origin" });
  return (await r.json()).find((x) => x.id === id) ?? null;
}, reportId);
check("archiving set archived_at", afterArchive && afterArchive.archived_at !== null);
check("archiving did NOT change the open/closed status",
  afterArchive && afterArchive.status === "open", `status=${afterArchive?.status}`);

// ------------------------------------------------ attachment access control
const attachmentId = afterArchive?.attachments?.[0]?.id ?? null;
check("the report carries its attachment in the API response", attachmentId !== null);

if (attachmentId) {
  const adminStatus = await adminPage.evaluate(async (aid) => {
    const r = await fetch(`/api/admin/bug-reports/attachments/${aid}`, { credentials: "same-origin" });
    return r.status;
  }, attachmentId);
  check("an admin can fetch the attachment", adminStatus === 200, `got ${adminStatus}`);

  // The reporter is a normal user. Even though it is THEIR OWN screenshot,
  // this route is admin-only -- and the point of the check is that an
  // unowned resource must not fall through to "readable by everyone".
  const userStatus = await page.evaluate(async (aid) => {
    const r = await fetch(`/api/admin/bug-reports/attachments/${aid}`, { credentials: "same-origin" });
    return r.status;
  }, attachmentId);
  check("a non-admin is refused the attachment (not silently allowed as an unowned resource)",
    userStatus === 403, `got ${userStatus}`);
}

// ------------------------------------------------ delete removes the files
const filesBefore = (afterArchive?.attachments ?? []).length;
check("the report has an attachment on record before deletion", filesBefore === 1, `${filesBefore}`);

await adminPage.locator('button:has-text("Delete report")').first().click();
await adminPage.waitForTimeout(400);
await adminPage.locator('button:has-text("Delete report")').last().click(); // confirm
await adminPage.waitForTimeout(1500);

const stillThere = await adminPage.evaluate(async (id) => {
  const r = await fetch("/api/admin/bug-reports", { credentials: "same-origin" });
  return (await r.json()).some((x) => x.id === id);
}, reportId);
check("deleting removes the report from the database", stillThere === false);

if (attachmentId) {
  const afterDelete = await adminPage.evaluate(async (aid) => {
    const r = await fetch(`/api/admin/bug-reports/attachments/${aid}`, { credentials: "same-origin" });
    return r.status;
  }, attachmentId);
  check("its attachment is gone too (cascade + the files on disk)",
    afterDelete === 404, `got ${afterDelete}`);
}

await deleteUserByUsername(adminCtx, username);
await browser.close();
process.exit(summary() ? 0 : 1);
