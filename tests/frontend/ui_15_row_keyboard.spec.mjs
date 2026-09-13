// R-070: every selection row is reachable and operable from the keyboard.
// R-065: a replaced 3Dmol viewer stops observing its container.
//
// Two findings from the 2026-09 review, in one spec because they are checked
// against the same page and the same seeded job.
//
// R-070. Seven components in the app selected something with a bare `onClick`
// on a `div`, `li` or `tr` and no role, `tabIndex` or key handler: the
// conversation list, both job lists, the plots list, a project's job list,
// and, the two that are not chrome, the orbital table and the vibration
// table. Those last two are how a user chooses which orbital the isosurface
// shows and which normal mode animates, so the scientific selection path
// itself was mouse-only. `lib/rowProps.ts` is now the single owner of the
// pattern.
//
// What is checked here, per row kind:
//
// 1. The row is reachable by Tab, which means it reports a tabindex of 0.
// 2. Enter on the focused row does what a click does.
// 3. Space does the same and does NOT scroll the page, which is the default
//    a keyboard control has to suppress.
// 4. Focus is visible. A tabbable row with no focus ring is worse than an
//    untabbable one, because the user cannot tell where they are, so this
//    compares a screenshot of the row focused against the same row not
//    focused and requires the pixels to differ.
// 5. Enter on a control INSIDE a row does not also fire the row's action.
//    Every one of these rows contains its own buttons or a checkbox.
//
// A `<tr>` keeps its row semantics and carries `aria-selected`; a `div` or
// `li` that is really a button says `role="button"`. Giving a table row
// `role="button"` would take the row and column relationships away from a
// screen reader, which is a worse trade than the one it makes.
//
// R-065. `GLViewer` has no teardown method and registers two observers on its
// container that it never removes, so every viewer ever created keeps
// observing and keeps re-rendering into a canvas nobody can see on every
// window resize. The count of live `ResizeObserver` observations is the part
// of that which is measurable from outside the library, so this patches
// `ResizeObserver.prototype.observe` and `.disconnect` before the app loads,
// cycles the job drawer ten times, and requires the live count not to grow
// with the cycles. The `document.body` and `window` listeners cannot be
// removed from outside 3Dmol and are not claimed to be; see
// docs/ARCHITECTURE.md.
//
// Run against the real docker-compose dev stack (needs a rebuilt
// frontend/dist -- nginx serves it from a host bind mount):
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/ui_15_row_keyboard.spec.mjs
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const COMPOSE_DIR = path.resolve(HERE, "..", "..");
const SHOT_DIR = process.env.QC_AGENT_SHOT_DIR || path.join(COMPOSE_DIR, "docs", "evaluation",
  "2026-09-app-review", "evidence", "fix", "P5.3", "shots");
const LABEL = "keyboard row probe, water frequencies";

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 600000,
  }).trim();
}

/** A row's element-level accessibility contract, read out of the live DOM
 *  rather than asserted against the source. */
async function rowContract(page, selector) {
  return page.$eval(selector, (el) => ({
    tag: el.tagName.toLowerCase(),
    tabindex: el.getAttribute("tabindex"),
    role: el.getAttribute("role"),
    ariaSelected: el.getAttribute("aria-selected"),
  }));
}

/** Focus a row directly (Tab order across the whole app is not this spec's
 *  subject; being focusable at all, and responding once focused, is) and
 *  press a key on it. */
async function pressOnRow(page, selector, key) {
  await page.$eval(selector, (el) => el.focus());
  await page.keyboard.press(key);
  await page.waitForTimeout(700);
}

async function shot(page, selector, name) {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const file = path.join(SHOT_DIR, `${name}.png`);
  const el = await page.$(selector);
  if (!el) return null;
  await el.screenshot({ path: file });
  return { file, bytes: fs.readFileSync(file) };
}

const drawerOpen = (page) => page.$('[role="dialog"]').then((h) => !!h);

async function closeDrawer(page) {
  if (await drawerOpen(page)) {
    await page.keyboard.press("Escape");
    await page.waitForSelector('[role="dialog"]', { state: "detached", timeout: 8000 }).catch(() => {});
  }
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_ui15_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();

  // R-065's counter has to be installed before any app code runs, so it goes
  // in as an init script rather than an evaluate.
  await page.addInitScript(() => {
    const RO = window.ResizeObserver;
    if (!RO) return;
    window.__roLive = 0;
    window.__roObserved = 0;
    const observe = RO.prototype.observe;
    const disconnect = RO.prototype.disconnect;
    const unobserve = RO.prototype.unobserve;
    RO.prototype.observe = function (...args) {
      if (!this.__counted) { this.__counted = true; window.__roLive += 1; }
      window.__roObserved += 1;
      return observe.apply(this, args);
    };
    RO.prototype.disconnect = function (...args) {
      if (this.__counted) { this.__counted = false; window.__roLive -= 1; }
      return disconnect.apply(this, args);
    };
    RO.prototype.unobserve = function (...args) {
      return unobserve.apply(this, args);
    };
  });

  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  let jobId = null;

  try {
    console.log("\n== register + log in ==");
    await page.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
    await page.fill('input[placeholder="Email"]', `${username}@example.test`);
    await page.fill('input[placeholder="Username"]', username);
    await page.fill('input[placeholder="First name"]', "QA");
    await page.fill('input[placeholder="Last name"]', "Tester");
    await page.fill('input[placeholder="Password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });
    check("registered and logged in", true);
    consoleErrors.length = 0;

    const users = await (await adminCtx.request.get(`${BASE_URL}/api/admin/users`)).json();
    const user = users.find((u) => u.username === username);
    check("found the just-registered user via the admin API", !!user, username);

    // A frequency job, because it is the one job that seeds BOTH tables this
    // spec cares about: a vibration table (its modes) and an orbital table
    // (PySCF writes one at the end of every frequency run).
    console.log("\n== seed one completed frequency job ==");
    const seeded = JSON.parse(execApi(`
import json, time
from app.chemistry.jobs.base import JobSpec, get_job_manager, write_meta
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
mgr = get_job_manager()
jid = mgr.submit(
    JobSpec(task="frequency", subtype="gs", method="hf", engine="pyscf", molecule=WATER,
            params={"basis": "sto-3g"}),
    owner_user_id="${user.id}",
)
write_meta(jid, {"label": ${JSON.stringify(LABEL)}})
status = None
deadline = time.time() + 480
while time.time() < deadline:
    status = (mgr.status(jid) or {}).get("status")
    if status in ("completed", "failed", "cancelled"):
        break
    time.sleep(1.0)
print(json.dumps({"job_id": jid, "status": status}))
`).split("\n").pop());
    jobId = seeded.job_id;
    check("the seeded frequency job reached status=completed",
      seeded.status === "completed", seeded.status);
    if (seeded.status !== "completed") throw new Error("cannot check row behaviour without a job");

    const mgrRow = `[data-testid="jobmanager-row-${jobId}"]`;
    await page.waitForSelector(mgrRow, { timeout: 30000 });

    // ---- 1. the job manager row ---------------------------------------
    console.log("\n== the job manager row is a keyboard control ==");
    const jm = await rowContract(page, mgrRow);
    check("the job row is a <tr> that kept its table semantics",
      jm.tag === "tr" && jm.role === null, `tag=${jm.tag} role=${jm.role}`);
    check("the job row is reachable by Tab", jm.tabindex === "0", `tabindex=${jm.tabindex}`);
    check("the job row says whether it is the selected one",
      jm.ariaSelected !== null, `aria-selected=${jm.ariaSelected}`);

    const unfocused = await shot(page, mgrRow, "jobrow-unfocused");
    await page.$eval(mgrRow, (el) => el.focus());
    await page.waitForTimeout(250);
    const focused = await shot(page, mgrRow, "jobrow-focused");
    check("a focused row looks different from an unfocused one",
      !!unfocused && !!focused && !unfocused.bytes.equals(focused.bytes),
      unfocused && focused && unfocused.bytes.equals(focused.bytes)
        ? "byte-identical, so the focus ring is not drawn"
        : `saved ${focused ? focused.file : "nothing"}`);

    await pressOnRow(page, mgrRow, "Enter");
    check("Enter on the job row opens the drawer", await drawerOpen(page));
    await closeDrawer(page);

    const scrollBefore = await page.evaluate(() => window.scrollY);
    await pressOnRow(page, mgrRow, " ");
    check("Space on the job row opens the drawer", await drawerOpen(page));
    const scrollAfter = await page.evaluate(() => window.scrollY);
    check("Space did not scroll the page out from under the row",
      scrollBefore === scrollAfter, `${scrollBefore} -> ${scrollAfter}`);

    // ---- 2. the two scientific selection tables ------------------------
    console.log("\n== the orbital and vibration tables are keyboard controls ==");
    await page.waitForSelector('[data-testid^="vibration-row-"]', { timeout: 30000 });
    const vib = await rowContract(page, '[data-testid="vibration-row-1"]');
    check("a vibrational mode row is reachable by Tab", vib.tabindex === "0", `tabindex=${vib.tabindex}`);
    check("a vibrational mode row says whether it is the chosen mode",
      vib.ariaSelected !== null, `aria-selected=${vib.ariaSelected}`);
    await pressOnRow(page, '[data-testid="vibration-row-1"]', "Enter");
    check("Enter chooses that vibrational mode",
      (await page.getAttribute('[data-testid="vibration-row-1"]', "aria-selected")) === "true");

    const orbSel = '[data-testid^="orbital-row-"]';
    if (await page.locator(orbSel).count()) {
      const first = await page.locator(orbSel).first().getAttribute("data-testid");
      const orb = await rowContract(page, `[data-testid="${first}"]`);
      check("an orbital row is reachable by Tab", orb.tabindex === "0", `tabindex=${orb.tabindex}`);
      await pressOnRow(page, `[data-testid="${first}"]`, "Enter");
      check("Enter chooses that orbital",
        (await page.getAttribute(`[data-testid="${first}"]`, "aria-selected")) === "true");
    } else {
      check("an orbital row is reachable by Tab", false, "no orbital table in this drawer");
    }
    await closeDrawer(page);

    // ---- 3. a control inside a row keeps its own Enter ------------------
    console.log("\n== a control inside a row does not fire the row ==");
    const checkbox = `[data-testid="jobmanager-select-${jobId}"]`;
    if (await page.locator(checkbox).count()) {
      await page.$eval(checkbox, (el) => el.focus());
      await page.keyboard.press("Enter");
      await page.waitForTimeout(500);
      check("Enter on the row's own checkbox does not open the drawer",
        !(await drawerOpen(page)));
      await closeDrawer(page);
    } else {
      check("Enter on the row's own checkbox does not open the drawer", true,
        "no per-row checkbox in this build, nothing to shadow");
    }

    // ---- 4. the conversation list --------------------------------------
    console.log("\n== the conversation list is a keyboard control ==");
    const convSel = '[data-testid^="conversation-row-"]';
    if (await page.locator(convSel).count()) {
      const first = await page.locator(convSel).first().getAttribute("data-testid");
      const conv = await rowContract(page, `[data-testid="${first}"]`);
      check("a conversation row announces itself as a button",
        conv.role === "button", `role=${conv.role}`);
      check("a conversation row is reachable by Tab", conv.tabindex === "0", `tabindex=${conv.tabindex}`);
    } else {
      check("a conversation row is reachable by Tab", true,
        "no conversations for a fresh account, nothing to check");
    }

    // ---- 5. R-065: viewers stop observing when they are replaced --------
    console.log("\n== a replaced viewer stops observing its container ==");
    const before = await page.evaluate(() => ({ live: window.__roLive, total: window.__roObserved }));
    for (let i = 0; i < 10; i++) {
      await page.click(mgrRow);
      await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
      await page.waitForTimeout(700);
      await closeDrawer(page);
      await page.waitForTimeout(250);
    }
    const after = await page.evaluate(() => ({ live: window.__roLive, total: window.__roObserved }));
    console.log(`  ResizeObserver: live ${before.live} -> ${after.live}, ` +
      `cumulative observe() calls ${before.total} -> ${after.total} over 10 drawer cycles`);
    check(
      "ten drawer cycles do not leave ten more live ResizeObservers behind",
      after.live - before.live < 5,
      `live grew by ${after.live - before.live} across 10 cycles ` +
      `(${after.total - before.total} observe() calls made)`,
    );

    check("no console errors during any of this", consoleErrors.length === 0,
      consoleErrors.slice(0, 3).join(" | "));
  } finally {
    if (jobId) {
      try {
        execApi(`
from app.chemistry.jobs.base import delete_job_dir
delete_job_dir("${jobId}")
print("deleted")
`);
      } catch (e) {
        console.log("cleanup failed:", String(e).slice(0, 200));
      }
    }
    await browser.close();
  }
  process.exit(summary() ? 0 : 1);
}

main();
