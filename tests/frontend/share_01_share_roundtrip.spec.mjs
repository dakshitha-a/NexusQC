/**
 * P6.1: the whole sharing workflow, driven end to end in a real browser
 * across TWO accounts in two independent browser contexts.
 *
 * Two contexts rather than two pages, because the app enforces one session
 * per user in Redis: a second login would kick the first, and the point of
 * this spec is that both people are looking at the app at once, which is
 * what sharing is for.
 *
 * The workflow: Alice finds Bob by name in the share picker, sends him a
 * copy of a job, Bob's rail shows a pending count, he accepts, and the copy
 * appears in his job manager carrying a "from alice" badge. Then the two
 * paths that must not copy anything -- Bob declines a second offer, and
 * Alice withdraws a third before he answers.
 *
 * The check that matters most is the last one: Alice deletes her original
 * and Bob's copy still opens. That is the requirement the whole feature
 * exists for, and it is the one that a reference-share implementation would
 * fail while passing everything above it.
 *
 * Console and page errors are collected throughout and an empty collection
 * is itself a check.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, randSuffix, summary,
} from "./_helpers.mjs";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PASSWORD = "correct horse battery staple 1";

function seedJob(userId, label) {
  const code = `
import time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.auth.models import record_ownership
m = resolve_molecule("water")
spec = JobSpec(method="hf", engine="pyscf", task="single_point", subtype="gs",
               molecule=m.to_dict(), params={"basis": "sto-3g"}, label=${JSON.stringify(label)})
job_id = get_job_manager().submit(spec)
for _ in range(90):
    if get_job_manager().status(job_id)["status"] in ("completed", "failed"):
        break
    time.sleep(1)
record_ownership("job", job_id, ${JSON.stringify(userId)})
print(job_id)
`;
  const out = execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code],
                           { cwd: REPO, encoding: "utf8", timeout: 180000 });
  return out.trim().split("\n").pop().trim();
}

async function registerIn(context, username, first, last, token, errors) {
  const page = await context.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`${username}: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`${username}: ${e.message}`));
  await page.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
  await page.fill('input[placeholder="Email"]', `${username}@example.test`);
  await page.fill('input[placeholder="Username"]', username);
  await page.fill('input[placeholder="First name"]', first);
  await page.fill('input[placeholder="Last name"]', last);
  await page.fill('input[placeholder="Password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });
  const me = await (await page.request.get(`${BASE_URL}/api/auth/me`)).json();
  return { page, me };
}

async function openShares(page) {
  if ((await page.locator('[data-testid="section-shares-panel"]').count()) === 0) {
    await page.click('[data-testid="section-shares-toggle"]');
  }
  await page.waitForSelector('[data-testid="section-shares-panel"]', { timeout: 10000 });
}

async function shareJobTo(page, jobId, recipientQuery, recipientUsername) {
  await page.click(`[data-testid="jobmanager-row-${jobId}"] input[type="checkbox"]`);
  await page.click('[data-testid="jobmanager-send-copy"]');
  await page.waitForSelector('[data-testid="share-dialog"]', { timeout: 10000 });
  await page.fill('[data-testid="share-user-search"]', recipientQuery);
  await page.waitForSelector(`[data-testid="share-user-${recipientUsername}"]`, { timeout: 10000 });
  await page.click(`[data-testid="share-user-${recipientUsername}"]`);
  await page.click('[data-testid="share-dialog-send"]');
  await page.waitForSelector('[data-testid="share-dialog-done"]', { timeout: 15000 });
  await page.click('[data-testid="share-dialog-done"]');
  // Leave the selection clean for the next share.
  const clear = page.locator('[data-testid="jobmanager-clear-selection"]');
  if (await clear.count()) await clear.click();
}

async function main() {
  const errors = [];
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);

  const aliceName = `qatest_${randSuffix()}`;
  const bobName = `qatest_${randSuffix()}`;
  const aliceCtx = await newContext(browser);
  const bobCtx = await newContext(browser);
  const jobIds = [];

  try {
    const alice = await registerIn(aliceCtx, aliceName, "Ada", "Lovelace",
                                   await mintInvite(adminCtx), errors);
    const bob = await registerIn(bobCtx, bobName, "Grace", "Hopper",
                                 await mintInvite(adminCtx), errors);
    check("both accounts registered and logged in", true);
    errors.length = 0;   // the pre-login /api/auth/me 401 is expected

    // --- The section exists, and starts quiet -------------------------
    await bob.page.waitForSelector('[data-testid="section-shares-toggle"]', { timeout: 15000 });
    check("the left rail has a Shared with me section", true);
    check("it starts collapsed, like the other rail sections",
          (await bob.page.locator('[data-testid="section-shares-panel"]').count()) === 0);
    await openShares(bob.page);
    check("an empty inbox says so",
          (await bob.page.locator('[data-testid="share-inbox-empty"]').innerText()).includes("Nothing waiting"));
    check("no pending badge when there is nothing pending",
          (await bob.page.locator('[data-testid="share-pending-count"]').count()) === 0);

    // --- Seed three jobs for Alice --------------------------------------
    const [j1, j2, j3] = ["qatest share one", "qatest share two", "qatest share three"]
      .map((label) => seedJob(alice.me.id, label));
    jobIds.push(j1, j2, j3);
    await alice.page.waitForFunction(
      (ids) => ids.every((id) => document.querySelector(`[data-testid="jobmanager-row-${id}"]`)),
      [j1, j2, j3], { timeout: 40000 },
    );
    check("Alice's three jobs are in her job manager", true);

    // --- Find a person by their REAL NAME, not their handle -------------
    await alice.page.click(`[data-testid="jobmanager-row-${j1}"] input[type="checkbox"]`);
    await alice.page.click('[data-testid="jobmanager-send-copy"]');
    await alice.page.waitForSelector('[data-testid="share-dialog"]', { timeout: 10000 });
    check("the share dialog says a copy is what gets sent",
          (await alice.page.locator('[data-testid="share-dialog"]').innerText()).toLowerCase().includes("copy"));
    await alice.page.fill('[data-testid="share-user-search"]', "Hopp");
    await alice.page.waitForSelector(`[data-testid="share-user-${bobName}"]`, { timeout: 10000 });
    check("a colleague is findable by surname, not only by username", true);
    const rowText = await alice.page.locator(`[data-testid="share-user-${bobName}"]`).innerText();
    check("the picker shows a human name", rowText.includes("Grace Hopper"), rowText.replace(/\n/g, " "));
    check("the picker does not show an email address", !rowText.includes("@"), rowText.replace(/\n/g, " "));
    await alice.page.click(`[data-testid="share-user-${bobName}"]`);
    await alice.page.fill('[data-testid="share-note"]', "the sto-3g one");
    await alice.page.click('[data-testid="share-dialog-send"]');
    await alice.page.waitForSelector('[data-testid="share-dialog-done"]', { timeout: 15000 });
    check("the offer is sent", true);
    await alice.page.click('[data-testid="share-dialog-done"]');
    await alice.page.locator('[data-testid="jobmanager-clear-selection"]').click();

    // --- It arrives, and nothing has been copied yet ---------------------
    await bob.page.waitForSelector('[data-testid="share-pending-count"]', { timeout: 20000 });
    check("a pending count appears in Bob's rail",
          (await bob.page.locator('[data-testid="share-pending-count"]').innerText()).trim() === "1");
    const offerText = await bob.page.locator('[data-testid^="share-offer-"]').first().innerText();
    check("the offer names the sender", offerText.includes(aliceName), offerText.replace(/\n/g, " | "));
    check("the offer shows how much space it would take", /\d+(\.\d+)?\s*(B|kB|MB|GB)/i.test(offerText));
    check("the offer carries the note", offerText.includes("the sto-3g one"));

    const bobJobsBefore = await bob.page.evaluate(async (base) => {
      const r = await fetch(`${base}/api/jobs`); return (await r.json()).length;
    }, BASE_URL);
    check("nothing has been copied into Bob's account yet", bobJobsBefore === 0,
          `${bobJobsBefore} job(s)`);

    // --- Accept ----------------------------------------------------------
    const offerId = await bob.page.locator('[data-testid^="share-offer-"]').first()
      .getAttribute("data-testid");
    const shareId = offerId.replace("share-offer-", "");
    await bob.page.click(`[data-testid="share-accept-${shareId}"]`);
    await bob.page.waitForFunction(
      () => document.querySelectorAll('[data-testid^="jobmanager-shared-badge-"]').length > 0,
      null, { timeout: 30000 },
    );
    check("accepting puts a copy in Bob's job manager", true);
    const badge = await bob.page.locator('[data-testid^="jobmanager-shared-badge-"]').first().innerText();
    check("the copy is badged with who sent it", badge.includes(aliceName), badge);
    const copyId = (await bob.page.locator('[data-testid^="jobmanager-shared-badge-"]').first()
      .getAttribute("data-testid")).replace("jobmanager-shared-badge-", "");
    jobIds.push(copyId);
    check("the copy has its own job id, not the sender's", copyId !== j1, `${j1} -> ${copyId}`);
    check("the inbox is quiet again",
          (await bob.page.locator('[data-testid="share-pending-count"]').count()) === 0);

    // --- Decline -----------------------------------------------------------
    await shareJobTo(alice.page, j2, "Hopp", bobName);
    await bob.page.waitForSelector('[data-testid="share-pending-count"]', { timeout: 20000 });
    const declineId = (await bob.page.locator('[data-testid^="share-offer-"]').first()
      .getAttribute("data-testid")).replace("share-offer-", "");
    await bob.page.click(`[data-testid="share-decline-${declineId}"]`);
    await bob.page.waitForFunction(
      () => document.querySelectorAll('[data-testid="share-pending-count"]').length === 0,
      null, { timeout: 20000 },
    );
    const afterDecline = await bob.page.evaluate(async (base) => {
      const r = await fetch(`${base}/api/jobs`); return (await r.json()).length;
    }, BASE_URL);
    check("declining copies nothing", afterDecline === 1, `${afterDecline} job(s), still just the accepted one`);

    // --- Withdraw ----------------------------------------------------------
    await shareJobTo(alice.page, j3, "Hopp", bobName);
    await bob.page.waitForSelector('[data-testid="share-pending-count"]', { timeout: 20000 });
    const outbox = await alice.page.evaluate(async (base) => {
      const r = await fetch(`${base}/api/shares/outbox`); return await r.json();
    }, BASE_URL);
    const pendingOut = outbox.find((s) => s.status === "pending");
    check("Alice's outbox shows the unanswered offer", !!pendingOut);
    await alice.page.evaluate(async ([base, id]) => {
      await fetch(`${base}/api/shares/${id}/withdraw`, { method: "POST" });
    }, [BASE_URL, pendingOut.share_id]);
    await bob.page.waitForFunction(
      () => document.querySelectorAll('[data-testid="share-pending-count"]').length === 0,
      null, { timeout: 20000 },
    );
    check("a withdrawn offer disappears from the recipient's inbox", true);

    // --- The requirement the feature exists for ---------------------------
    await alice.page.evaluate(async ([base, id]) => {
      await fetch(`${base}/api/jobs/${id}`, { method: "DELETE" });
    }, [BASE_URL, j1]);
    const stillThere = await bob.page.evaluate(async ([base, id]) => {
      const r = await fetch(`${base}/api/jobs/${id}`); return r.status;
    }, [BASE_URL, copyId]);
    check("Bob's copy survives Alice deleting her original", stillThere === 200,
          `GET /api/jobs/${copyId} -> ${stillThere}`);

    check("no console or page errors during the whole workflow",
          errors.length === 0, errors.slice(0, 4).join(" | "));
  } finally {
    // Delete the copies and originals this spec created, then the users.
    for (const id of jobIds) {
      try {
        const p = await adminCtx.newPage();
        await p.request.delete(`${BASE_URL}/api/jobs/${id}`, { headers: { Origin: BASE_URL } });
        await p.close();
      } catch { /* already gone */ }
    }
    await deleteUserByUsername(adminCtx, aliceName);
    await deleteUserByUsername(adminCtx, bobName);
    await browser.close();
  }

  process.exit(summary() ? 0 : 1);
}

main();
