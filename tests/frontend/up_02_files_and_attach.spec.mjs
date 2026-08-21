// Phase 3 (P3.4): the Files panel and the composer's attach-a-geometry
// flow, driven in a real browser -- CLAUDE.md requires this for anything
// the molecule viewer renders (a code read has silently missed real bugs
// here before; see the React Strict Mode WebGL leak note in
// docs/ARCHITECTURE.md). Frame cycling and per-frame tagging are verified
// by diffing canvas.toDataURL(), never page.screenshot() (which can't
// reliably capture WebGL canvas content).
//
// Run against the real docker-compose dev stack (needs a registered user,
// a real conversation, and a rebuilt frontend/dist -- nginx serves it from
// a host bind mount, so `npm run build` must have run before this):
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/up_02_files_and_attach.spec.mjs
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, deleteUserByUsername, check, summary, BASE_URL,
} from "./_helpers.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const WATER_XYZ =
  "3\nwater\nO  0.000000  0.000000  0.117300\nH  0.000000  0.757200 -0.469200\nH  0.000000 -0.757200 -0.469200\n";
const PAIR_XYZ =
  WATER_XYZ + "3\nwater stretched\nO  0.000000  0.000000  0.200000\nH  0.000000  0.800000 -0.500000\nH  0.000000 -0.800000 -0.500000\n";
const SET_XYZ =
  PAIR_XYZ + "3\nwater bent\nO  0.000000  0.000000  0.300000\nH  0.000000  0.850000 -0.550000\nH  0.000000 -0.850000 -0.550000\n";

function writeTemp(name, content) {
  const p = path.join(__dirname, name);
  writeFileSync(p, content);
  return p;
}

// A canvas.toDataURL() snapshot of the FIRST currently-visible <canvas> in
// `scope` (a Playwright locator, or the page itself) -- page.screenshot()
// can't reliably capture WebGL content, per CLAUDE.md.
async function canvasSnapshot(scope) {
  return scope.evaluate(() => {
    const canvases = Array.from(document.querySelectorAll("canvas")).filter((c) => c.offsetParent !== null);
    const c = canvases[canvases.length - 1];
    return c ? c.toDataURL() : null;
  });
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_up02_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  page.on("response", (r) => {
    if (r.status() >= 400) consoleErrors.push(`HTTP ${r.status()} ${r.request().method()} ${r.url()}`);
  });

  const waterPath = writeTemp("_up02_water.xyz", WATER_XYZ);
  const pairPath = writeTemp("_up02_pair.xyz", PAIR_XYZ);
  const setPath = writeTemp("_up02_set.xyz", SET_XYZ);

  try {
    console.log("\n== register + log in ==");
    await page.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
    await page.fill('input[placeholder="Email"]', `${username}@example.test`);
    await page.fill('input[placeholder="Username"]', username);
    await page.fill('input[placeholder="First name"]', "QA");
    await page.fill('input[placeholder="Last name"]', "Tester");
    await page.fill('input[placeholder="Password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 15000 });
    check("registered and logged in", true);

    console.log("\n== open a conversation, then the Files panel ==");
    await page.click('button[title="New conversation"]');
    await page.waitForTimeout(500); // activeThreadId settles client-side, no network round trip to await
    await page.click('button:has-text("Files")');
    await page.waitForSelector('[data-testid="files-drop-zone"]', { timeout: 10000 });
    check("Files panel expands", await page.isVisible('[data-testid="files-drop-zone"]'));

    console.log("\n== upload a 2-geometry xyz ==");
    await page.click('button[title="Add file"]');
    const fileInput = page.locator('[data-testid="files-section-file-input"]');
    await fileInput.setInputFiles(pairPath);
    await page.click('button:has-text("Add")');
    await page.waitForSelector('[data-testid="upload-row"]:has-text("_up02_pair.xyz")', { timeout: 15000 });
    check("uploaded file appears in the list", await page.isVisible('[data-testid="upload-row"]:has-text("_up02_pair.xyz")'));
    const pairRow = page.locator('[data-testid="upload-row"]:has-text("_up02_pair.xyz")');
    const pairRowText = await pairRow.textContent();
    check("the 2-geometry upload is sniffed as a pair", /2 geometries \(pair\)/.test(pairRowText ?? ""), pairRowText ?? "");

    console.log("\n== attach it: 2 geometries become molecule frames ==");
    await pairRow.locator('[data-testid="upload-attach"]').click();
    await page.waitForSelector("canvas", { timeout: 15000 });
    await page.waitForTimeout(800); // WebGL render settle
    const afterAttach = await canvasSnapshot(page);
    check("a molecule canvas renders after attach", !!afterAttach);

    console.log("\n== cycle frames in the molecule panel (canvas diff) ==");
    // The panel auto-jumps to the NEWEST frame whenever the frame count
    // changes (see MoleculePanel's own effect), so after attaching 2
    // frames the stepper already sits on frame 2/2 -- "frame-prev" (not
    // "frame-next") is the one guaranteed enabled here.
    await page.click('[data-testid="frame-prev"]');
    await page.waitForTimeout(800);
    const afterCycle = await canvasSnapshot(page);
    check(
      "the canvas changes after stepping to the next frame",
      afterCycle !== null && afterCycle !== afterAttach,
      "toDataURL() was identical before/after stepping",
    );

    console.log("\n== upload + attach a 3-geometry xyz: becomes a geometry_set job ==");
    await page.click('button[title="Add file"]');
    const fileInput2 = page.locator('[data-testid="files-section-file-input"]');
    await fileInput2.setInputFiles(setPath);
    await page.click('button:has-text("Add")');
    await page.waitForSelector('[data-testid="upload-row"]:has-text("_up02_set.xyz")', { timeout: 15000 });
    const setRow = page.locator('[data-testid="upload-row"]:has-text("_up02_set.xyz")');
    const setRowText = await setRow.textContent();
    check("the 3-geometry upload is sniffed as a set", /3 geometries \(set\)/.test(setRowText ?? ""), setRowText ?? "");

    const [attachResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/attach_upload") && r.request().method() === "POST", { timeout: 15000 }),
      setRow.locator('[data-testid="upload-attach"]').click(),
    ]);
    const attachBody = await attachResponse.json();
    check("attaching 3 geometries returns kind=geometry_set with a job_id", attachBody.kind === "geometry_set" && !!attachBody.job_id, JSON.stringify(attachBody));
    const geometrySetJobId = attachBody.job_id;

    await page.waitForSelector(`text=/geometry set of 3 geometries/`, { timeout: 15000 });
    check("a notice message announces the geometry set in the conversation", true);

    console.log("\n== open the geometry_set job's drawer ==");
    // Waited for explicitly (not just clicked immediately): the notice
    // message arrives over SSE the instant attach_upload responds, but
    // the jobs list panel refetches via a separate React Query
    // invalidation that can lag it slightly.
    await page.waitForSelector('text=/Uploaded geometry set \\(3 frames\\)/', { timeout: 15000 });
    // The label cell's own <div> calls e.stopPropagation() (JobManagerPanel.tsx
    // supports double-click-to-rename there), and Playwright clicks a
    // locator at its bounding-box center -- for the <tr>, that lands
    // inside the wide label cell and inherits the same stopped
    // propagation. The status-dot cell (2nd column) has no such handler,
    // confirmed directly against the real DOM (not assumed) after the
    // <tr>-click approach silently opened nothing.
    const jobRow = page.locator('tr:has-text("Uploaded geometry set (3 frames)")').first();
    await jobRow.locator("td").nth(1).click({ timeout: 15000 });
    await page.waitForSelector('[role="dialog"]', { timeout: 10000 });
    await page.waitForSelector('[role="dialog"] canvas', { timeout: 15000 });
    await page.waitForTimeout(800);
    check("the drawer shows a geometry count heading", await page.isVisible("text=/3 geometries/"));
    const drawerFrame0 = await canvasSnapshot(page.locator('[role="dialog"]'));

    console.log("\n== cycle the geometry_set viewer's frames (canvas diff) ==");
    // Same auto-jump-to-newest-frame reasoning does NOT apply here --
    // GeometrySetViewer starts at frameIndex 0 (no such effect), so
    // "frame-next" is the enabled one.
    await page.click('[role="dialog"] [data-testid="frame-next"]');
    await page.waitForTimeout(800);
    const drawerFrame1 = await canvasSnapshot(page.locator('[role="dialog"]'));
    check(
      "the drawer canvas changes after stepping to the next geometry",
      drawerFrame1 !== null && drawerFrame1 !== drawerFrame0,
      "toDataURL() was identical before/after stepping in the drawer",
    );

    console.log("\n== tag a geometry into the active molecule ==");
    const [tagResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/tag_job_frame") && r.request().method() === "POST", { timeout: 15000 }),
      page.click('[data-testid="geometry-set-tag-frame"]'),
    ]);
    check("tagging a frame succeeds (200)", tagResponse.status() === 200, String(tagResponse.status()));
    await page.waitForTimeout(800);

    console.log("\n== delete one uploaded file ==");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    // The Files section is a plain toggle, already expanded from earlier
    // in this run -- only click to open it if it's actually collapsed,
    // rather than assuming its state and toggling it shut by accident.
    if (!(await page.isVisible('[data-testid="files-drop-zone"]'))) {
      await page.click('button:has-text("Files")');
    }
    await page.waitForSelector('[data-testid="files-drop-zone"]', { timeout: 10000 });
    await page.click('button[title="Add file"]');
    await page.locator('[data-testid="files-section-file-input"]').setInputFiles(waterPath);
    await page.click('button:has-text("Add")');
    await page.waitForSelector('[data-testid="upload-row"]:has-text("_up02_water.xyz")', { timeout: 15000 });
    check("a third file (single geometry) uploads for the delete/clear-all checks", true);
    const waterRow = page.locator('[data-testid="upload-row"]:has-text("_up02_water.xyz")');
    await waterRow.hover();
    await waterRow.locator('[data-testid="upload-delete"]').click();
    await page.waitForSelector('[data-testid="upload-row"]:has-text("_up02_water.xyz")', { state: "detached", timeout: 10000 });
    check("the deleted file disappears from the list", true);

    console.log("\n== clear-all requires a two-click confirm ==");
    const remainingBefore = await page.locator('[data-testid="upload-row"]').count();
    check("at least one file remains before clear-all", remainingBefore > 0, String(remainingBefore));
    await page.click('[data-testid="files-clear-all"]');
    check(
      "the first click arms a confirm step, not an immediate delete",
      await page.isVisible('[data-testid="files-clear-all-confirm"]'),
    );
    const stillThereAfterArm = await page.locator('[data-testid="upload-row"]').count();
    check("nothing is deleted yet after only the first click", stillThereAfterArm === remainingBefore, `${stillThereAfterArm} vs ${remainingBefore}`);
    await page.click('[data-testid="files-clear-all-confirm-yes"]');
    await page.waitForSelector('[data-testid="upload-row"]', { state: "detached", timeout: 10000 }).catch(() => {});
    const remainingAfter = await page.locator('[data-testid="upload-row"]').count();
    check("clear-all removes every remaining file after confirming", remainingAfter === 0, String(remainingAfter));

    // GET /api/auth/me 401s once, harmlessly, before login on every
    // anonymous page load -- api.ts's own comment documents this as
    // AuthGate's expected initial-state check, not a bug. Confirmed via
    // the response listener above that the ONLY 401 in this run is that
    // exact request; the browser's own generic "Failed to load resource"
    // console line for the same event carries no URL (a known Chrome
    // limitation -- see draft_01_approval_card.spec.mjs's own comment on
    // this), so it's filtered by its fixed text rather than by URL.
    const realErrors = consoleErrors.filter(
      (e) => !e.includes("/api/auth/me") && !/Failed to load resource.*401/.test(e),
    );
    check("no uncaught console/page errors during the whole flow", realErrors.length === 0, realErrors.join(" | "));
  } catch (err) {
    check("spec ran to completion without throwing", false, String(err?.stack ?? err));
  } finally {
    try {
      unlinkSync(waterPath);
      unlinkSync(pairPath);
      unlinkSync(setPath);
    } catch {
      /* best-effort cleanup */
    }
    await deleteUserByUsername(adminCtx, username);
    await browser.close();
  }

  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main();
