/**
 * P6.2: every component this feature adds actually RENDERS, in the states a
 * real user reaches, and none of them break the rail's layout.
 *
 * Written because "the workflow passes" and "the UI is sound" are different
 * claims. share_01 drives the happy path and would go green even if the
 * inbox row overflowed the rail, the dialog blew up at a narrow width, or a
 * PanelErrorBoundary quietly swallowed the whole section. Three things get
 * checked here that a workflow spec cannot see:
 *
 *   * The collapsed rail. leftRailCollapsed is persisted, so a collapsed
 *     strip is the state a returning user actually lands in -- proj_03
 *     caught Files missing from that strip entirely for exactly this
 *     reason, so the Shared with me icon is asserted after a RELOAD, not
 *     just after a toggle.
 *   * Both extremes of the rail's drag range, 220px and 520px, with a long
 *     sender name and a long job label. Nothing may push the page into a
 *     horizontal scroll.
 *   * No PanelErrorBoundary fallback anywhere, at any point.
 *
 * Uses a real pending offer rather than an empty inbox, because the empty
 * state is the easy one and the offer row is what carries the overflow risk.
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

// Long enough to overflow a 220px rail several times over, which is the
// point: the row must truncate rather than widen the page.
const LONG_LABEL =
  "qatest a deliberately overlong job label that no rail width can accommodate without truncating it";

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

async function boundaryFallbacks(page) {
  return page.evaluate(() =>
    /Something went wrong|failed to render|couldn't be displayed/i.test(document.body.innerText));
}

async function pageScrollsSideways(page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
}

async function openShares(page) {
  await page.waitForSelector('[data-testid="section-shares-toggle"]', { timeout: 15000 });
  if ((await page.locator('[data-testid="section-shares-panel"]').count()) === 0) {
    await page.click('[data-testid="section-shares-toggle"]');
    await page.waitForSelector('[data-testid="section-shares-panel"]', { timeout: 10000 });
  }
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
    errors.length = 0;
    const page = bob.page;

    // --- The empty state renders -------------------------------------
    await openShares(page);
    check("the Shared with me section renders",
          await page.locator('[data-testid="section-shares-panel"]').isVisible());
    check("the empty inbox renders its own state",
          await page.locator('[data-testid="share-inbox-empty"]').isVisible());
    check("aria-expanded is correct when open",
          (await page.locator('[data-testid="section-shares-toggle"]').getAttribute("aria-expanded")) === "true");
    await page.click('[data-testid="section-shares-toggle"]');
    check("aria-expanded is correct when closed",
          (await page.locator('[data-testid="section-shares-toggle"]').getAttribute("aria-expanded")) === "false");
    await openShares(page);

    // --- The share dialog renders -------------------------------------
    const jobId = seedJob(alice.me.id, LONG_LABEL);
    jobIds.push(jobId);
    await alice.page.waitForSelector(`[data-testid="jobmanager-row-${jobId}"]`, { timeout: 40000 });
    await alice.page.click(`[data-testid="jobmanager-row-${jobId}"] input[type="checkbox"]`);
    await alice.page.click('[data-testid="jobmanager-send-copy"]');
    await alice.page.waitForSelector('[data-testid="share-dialog"]', { timeout: 10000 });
    check("the share dialog renders",
          await alice.page.locator('[data-testid="share-dialog"]').isVisible());
    check("the search field is focused on open, so typing just works",
          await alice.page.evaluate(() =>
            document.activeElement?.getAttribute("data-testid") === "share-user-search"));
    check("Send is disabled until somebody is picked",
          await alice.page.locator('[data-testid="share-dialog-send"]').isDisabled());
    await alice.page.fill('[data-testid="share-user-search"]', "zzzznobody");
    await alice.page.waitForSelector('[data-testid="share-user-none"]', { timeout: 10000 });
    check("a query matching nobody renders an explicit empty state", true);
    await alice.page.fill('[data-testid="share-user-search"]', bobName.slice(0, 8));
    await alice.page.waitForSelector(`[data-testid="share-user-${bobName}"]`, { timeout: 10000 });
    await alice.page.click(`[data-testid="share-user-${bobName}"]`);
    check("picking somebody enables Send",
          !(await alice.page.locator('[data-testid="share-dialog-send"]').isDisabled()));
    await alice.page.click('[data-testid="share-dialog-send"]');
    await alice.page.waitForSelector('[data-testid="share-dialog-done"]', { timeout: 15000 });
    check("the sent state explains that nothing has been copied yet",
          (await alice.page.locator('[data-testid="share-dialog"]').innerText()).toLowerCase()
            .includes("accept"));
    await alice.page.click('[data-testid="share-dialog-done"]');
    check("no boundary fallback on the sender's page", !(await boundaryFallbacks(alice.page)));

    // --- The offer row renders, and the badge counts ------------------
    await page.waitForSelector('[data-testid="share-pending-count"]', { timeout: 20000 });
    check("the pending badge renders with a count",
          (await page.locator('[data-testid="share-pending-count"]').innerText()).trim() === "1");
    check("the offer row renders",
          await page.locator('[data-testid^="share-offer-"]').first().isVisible());
    check("both Accept and Decline render",
          (await page.locator('[data-testid^="share-accept-"]').count()) === 1 &&
          (await page.locator('[data-testid^="share-decline-"]').count()) === 1);

    // --- Rail widths ---------------------------------------------------
    const railWidth = async () =>
      page.evaluate(() => {
        const el = document.querySelector('[data-testid="section-shares-toggle"]');
        return el ? el.closest("div.flex.min-w-0.shrink-0.flex-col").getBoundingClientRect().width : null;
      });
    const setRail = async (width) => {
      await page.evaluate((w) => {
        const raw = localStorage.getItem("qc-agent-layout");
        const parsed = raw ? JSON.parse(raw) : { state: {}, version: 0 };
        parsed.state = { ...parsed.state, leftRailWidth: w, leftRailCollapsed: false };
        localStorage.setItem("qc-agent-layout", JSON.stringify(parsed));
      }, width);
      await page.reload({ waitUntil: "domcontentloaded" });
      await openShares(page);
      await page.waitForSelector('[data-testid^="share-offer-"]', { timeout: 20000 });
    };

    for (const w of [220, 520]) {
      await setRail(w);
      check(`the rail really is at ${w}px`, Math.round(await railWidth()) === w,
            String(await railWidth()));
      check(`the offer row renders at ${w}px`,
            await page.locator('[data-testid^="share-offer-"]').first().isVisible());
      const box = await page.locator('[data-testid^="share-offer-"]').first().boundingBox();
      check(`the offer row stays inside the rail at ${w}px`, box.width <= w,
            `row ${Math.round(box.width)}px in a ${w}px rail`);
      check(`no horizontal page scroll at ${w}px`, !(await pageScrollsSideways(page)));
      check(`no boundary fallback at ${w}px`, !(await boundaryFallbacks(page)));
    }

    // --- The collapsed rail, after a reload ----------------------------
    await page.evaluate(() => {
      const raw = localStorage.getItem("qc-agent-layout");
      const parsed = raw ? JSON.parse(raw) : { state: {}, version: 0 };
      parsed.state = { ...parsed.state, leftRailCollapsed: true };
      localStorage.setItem("qc-agent-layout", JSON.stringify(parsed));
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });
    check("the collapsed rail still offers a Shared with me icon",
          (await page.locator('[data-testid="rail-collapsed-shares"]').count()) > 0,
          "leftRailCollapsed persists, so this is the state a returning user lands in");
    check("Projects is still there beside it, unbroken",
          (await page.locator('[data-testid="rail-collapsed-projects"]').count()) > 0);
    await page.click('[data-testid="rail-collapsed-shares"]');
    await page.waitForSelector('[data-testid="section-shares-panel"]', { timeout: 10000 });
    check("clicking it expands the rail AND opens the section",
          await page.locator('[data-testid="section-shares-panel"]').isVisible());
    check("no boundary fallback after the collapsed-rail round trip",
          !(await boundaryFallbacks(page)));

    check("no console or page errors throughout", errors.length === 0,
          errors.slice(0, 4).join(" | "));
  } finally {
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
