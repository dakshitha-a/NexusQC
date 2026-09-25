// The update notice, the lockout overlay, and the console's update controls,
// in a real browser.
//
// Nothing here starts, schedules or cancels a real update. The stack this runs
// against is also a research group's deployment, and a notice is something
// every one of them would see. So /api/notice, and for the console part the
// deployment and activity routes, are answered by page.route inside this
// browser only, and the POST the console makes is caught and answered here
// too; the spec checks what the page would have sent.
//
//   1. Banner, signed in as a fresh test user: absent when there is no
//      notice; for scheduled, overdue, waiting_for_jobs, imminent, a --force
//      update, done and cancelled it renders the sentence for that phase and
//      the administrator's note; done can be dismissed and stays dismissed
//      after a reload.
//   2. Banner on the sign-in screen, signed out: scheduled renders there too.
//   3. Overlay: an in_progress notice raises it before any request answers
//      503, and it does not reload the page while /api/notice still reports
//      the lockout; once the lockout is reported lifted, it reloads.
//   4. Console, as the test admin, with a live runner and one user running
//      calculations mocked: the notice fields render with 10 minutes and an
//      empty note; a cancel button shows while an update is announced and
//      sends {action: "cancel"}; the stop-and-update override names the user
//      whose calculations would stop; typing UPDATE sends the notice minutes
//      and the note the admin entered.
//
// Screenshots of every state go to a temporary directory printed at the end.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, deleteUserByUsername, openUserMenu,
  check, summary, BASE_URL, LOGGED_IN, randSuffix,
} from "./_helpers.mjs";

const ORIGIN = { headers: { Origin: BASE_URL } };
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "notice01-"));
const now = () => Date.now() / 1000;

function noticeRoute(ctx, getNotice, maintenance = () => false) {
  return ctx.route("**/api/notice", (r) => r.fulfill({
    json: { notice: getNotice(), maintenance: maintenance(), now: now() },
  }));
}

function notice(id, extra) {
  return { id, commit: "abc1234", message: "", waiting_jobs: 0, stops_running_jobs: false,
           updated_at: now() - 30, expires_at: now() + 3600, restart_at: now() + 452, ...extra };
}

const browser = await newBrowser();
const admin = await newContext(browser);
await adminApiLogin(admin);
const username = "qatest_n01_" + randSuffix(6);

try {
  // A fresh test user, registered through the api, which signs this context in.
  const userCtx = await newContext(browser);
  const token = await mintInvite(admin);
  const reg = await userCtx.request.post(`${BASE_URL}/api/auth/register`, {
    ...ORIGIN,
    data: { invite_token: token, email: `${username}@example.test`, username,
            password: "notice-01 passphrase long enough", first_name: "QA", last_name: "Notice" },
  });
  check("a test user is registered", reg.ok(), `${reg.status()}`);

  // --- 1. the banner, signed in ------------------------------------------
  let current = null;
  await noticeRoute(userCtx, () => current);
  const page = await userCtx.newPage();
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  const banner = page.locator('[data-testid="update-notice"]');
  await page.waitForTimeout(1500);
  check("no banner when no update is announced", (await banner.count()) === 0);

  const cases = [
    ["scheduled", notice("n-sched", { phase: "scheduled", message: "Brings update notices." }),
      ["will restart for an update at", "(in 7m", "running calculations are not interrupted", "queue"]],
    ["overdue", notice("n-over", { phase: "scheduled", restart_at: now() - 90 }),
      ["shortly, once the update is ready", "minute's warning"]],
    ["waiting", notice("n-wait", { phase: "waiting_for_jobs", waiting_jobs: 2 }),
      ["waiting for 2 running calculations", "queue"]],
    ["imminent", notice("n-imm", { phase: "imminent", restart_at: now() + 50 }),
      ["about to restart", "stay signed in"]],
    ["forced", notice("n-force", { phase: "scheduled", stops_running_jobs: true }),
      ["will be stopped"]],
    ["cancelled", notice("n-canc", { phase: "cancelled" }), ["was cancelled"]],
    ["done", notice("n-done", { phase: "done" }), ["was updated at"]],
  ];
  for (const [name, n, phrases] of cases) {
    current = n;
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="update-notice"]', { timeout: 20000 });
    const text = await banner.innerText();
    check(`${name}: the banner says what this phase means`,
          phrases.every((p) => text.includes(p)), text.slice(0, 220));
    check(`${name}: it carries the phase`, (await banner.getAttribute("data-phase")) === n.phase);
    if (n.message) {
      check(`${name}: and the administrator's note`, text.includes(`From the administrator: ${n.message}`), text);
    }
    await page.screenshot({ path: path.join(outDir, `banner-${name}.png`) });
  }
  const dismiss = page.locator('[data-testid="update-notice-dismiss"]');
  check("done can be dismissed", (await dismiss.count()) === 1);
  await dismiss.click();
  await page.waitForTimeout(300);
  check("and it goes", (await banner.count()) === 0);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await page.waitForTimeout(1500);
  check("and stays gone after a reload", (await banner.count()) === 0);

  // --- 2. the sign-in screen ------------------------------------------------
  const anon = await newContext(browser);
  await noticeRoute(anon, () => notice("n-login", { phase: "scheduled" }));
  const lp = await anon.newPage();
  await lp.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await lp.waitForSelector('[data-testid="update-notice"]', { timeout: 20000 });
  check("the banner shows on the sign-in screen too",
        (await lp.locator('input[placeholder="Password"]').count()) === 1
        && (await lp.locator('[data-testid="update-notice"]').innerText()).includes("will restart"));
  await lp.screenshot({ path: path.join(outDir, "banner-signin.png") });
  await anon.close();

  // --- 3. the overlay waits for the lockout to lift --------------------------
  let locked = true;
  current = notice("n-prog", { phase: "in_progress" });
  await userCtx.unroute("**/api/notice");
  await noticeRoute(userCtx, () => current, () => locked);
  let reloads = 0;
  page.on("load", () => { reloads += 1; });
  // Wait for this reload's own load event before counting from it, or the
  // count starts one short and the overlay is blamed for the spec's reload.
  await page.reload({ waitUntil: "load" });
  const before = reloads;
  // No request answers 503 yet: the notice alone must raise the overlay,
  // because while the api is recreated nginx answers with gateway errors.
  await page.waitForSelector("text=NexusQC is being updated", { timeout: 15000 });
  check("the in_progress notice alone raises the overlay, before any 503", true);
  await userCtx.route("**/api/jobs**", (r) => (locked
    ? r.fulfill({ status: 503, json: { detail: "maintenance", message: "NexusQC is being updated and will be back shortly." } })
    : r.continue()));
  check("it tells the user they stay signed in",
        (await page.locator("text=You stay signed in").count()) > 0);
  await page.screenshot({ path: path.join(outDir, "overlay.png") });
  await page.waitForTimeout(9000);
  check("it does not reload while the lockout is still on", reloads === before, `${reloads - before} reload(s)`);
  locked = false;
  current = notice("n-done2", { phase: "done" });
  const t0 = Date.now();
  while (reloads === before && Date.now() - t0 < 30000) await page.waitForTimeout(500);
  check("it reloads once the lockout is reported lifted", reloads > before, `${reloads - before} reload(s)`);
  await userCtx.unroute("**/api/jobs**");

  // --- 4. the console ---------------------------------------------------------
  let announced = null;
  const sent = [];
  await noticeRoute(admin, () => announced);
  await admin.route("**/api/admin/deployment", async (r) => {
    const real = await (await r.fetch()).json();
    await r.fulfill({ json: { ...real, runner: { installed: true, alive: true, last_seen: now(), age_seconds: 5 } } });
  });
  await admin.route("**/api/admin/activity", (r) => r.fulfill({ json: {
    users: [{ id: "u1", username: "qatest_n01_chemist", email: null, role: "user", is_active: true,
              last_login_at: null, running_jobs: 2, pending_jobs: 0, open_streams: 1,
              would_be_interrupted: true, is_you: false }],
    unowned: { running_jobs: 0, pending_jobs: 0, open_streams: 0 },
    totals: { running_jobs: 2, pending_jobs: 0, open_streams: 1, users_interrupted: 1, others_interrupted: 1 },
  } }));
  await admin.route("**/api/admin/deploy", async (r) => {
    if (r.request().method() !== "POST") return r.continue();
    const body = r.request().postDataJSON();
    sent.push(body);
    await r.fulfill({ json: { id: "notice01fake", action: body.action } });
  });
  await admin.route("**/api/admin/deploy/notice01fake", (r) => r.fulfill({ json: {
    id: "notice01fake", status: { state: "running", step: "waiting for the announced restart time" },
    request: { action: "update" }, report: null, changes: [], log: "" } }));

  const ap = await admin.newPage();
  await ap.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await ap.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await openUserMenu(ap);
  await ap.locator('[data-testid="admin-open"]').click();
  await ap.waitForSelector("text=Admin console", { timeout: 10000 });
  await ap.locator('[data-testid="admin-nav-deployment"]').click();
  await ap.waitForSelector('[data-testid="deploy-notice-settings"]', { timeout: 15000 });
  const minutes = ap.locator('[data-testid="deploy-notice-minutes"]');
  check("the notice settings render with 10 minutes", (await minutes.inputValue()) === "10");
  check("and an empty note", (await ap.locator('[data-testid="deploy-notice-message"]').inputValue()) === "");
  check("no cancel button while nothing is announced", (await ap.locator('[data-testid="deploy-cancel"]').count()) === 0);

  const force = ap.locator('[data-testid="deploy-update-force"]');
  await ap.waitForSelector('[data-testid="deploy-update-force"]', { timeout: 10000 });
  const forceText = await ap.locator("div.rounded", { has: force }).last().innerText();
  check("the stop-and-update override is offered while calculations run", (await force.count()) > 0);
  check("and names whose calculations would stop", forceText.includes("qatest_n01_chemist (2)"), forceText.slice(0, 300));
  await ap.screenshot({ path: path.join(outDir, "console-controls.png"), fullPage: true });

  await minutes.fill("25");
  await ap.locator('[data-testid="deploy-notice-message"]').fill("Brings update notices.");
  const updateButton = ap.locator('[data-testid="deploy-update"]');
  check("the Update button says Update, not Purge", (await updateButton.innerText()).trim() === "Update",
        await updateButton.innerText());
  check("and stays disabled until the phrase is typed", await updateButton.isDisabled());
  await ap.locator('[data-testid="deploy-update-phrase"]').fill("UPDATE");
  await updateButton.click();
  const t1 = Date.now();
  while (!sent.some((b) => b.action === "update") && Date.now() - t1 < 10000) await ap.waitForTimeout(200);
  const upd = sent.find((b) => b.action === "update");
  check("typing UPDATE sends an update", Boolean(upd), JSON.stringify(sent));
  check("with the notice minutes and note the admin entered",
        upd && upd.notice_minutes === 25 && upd.message === "Brings update notices." && upd.drain === true,
        JSON.stringify(upd));

  announced = notice("n-console", { phase: "scheduled" });
  await ap.reload({ waitUntil: "domcontentloaded" });
  await ap.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await openUserMenu(ap);
  await ap.locator('[data-testid="admin-open"]').click();
  await ap.locator('[data-testid="admin-nav-deployment"]').click();
  await ap.waitForSelector('[data-testid="deploy-cancel"]', { timeout: 20000 });
  check("a cancel button shows while an update is announced", true);
  check("and Update is held while one is announced, so a second cannot queue behind it",
        await ap.locator('[data-testid="deploy-update"]').isDisabled());
  await ap.screenshot({ path: path.join(outDir, "console-cancel.png"), fullPage: true });
  await ap.locator('[data-testid="deploy-cancel"]').click();
  const t2 = Date.now();
  while (!sent.some((b) => b.action === "cancel") && Date.now() - t2 < 10000) await ap.waitForTimeout(200);
  check("and it sends a cancel", sent.some((b) => b.action === "cancel"), JSON.stringify(sent));
} finally {
  await deleteUserByUsername(admin, username).catch(() => {});
  await browser.close();
  console.log(`\nscreenshots: ${outDir}`);
}
summary();
