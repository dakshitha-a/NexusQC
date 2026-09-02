// One switch turns the atom numbers off in every 3D viewer, and the images
// the viewers export follow it.
//
// Nothing here can be settled by reading the code. The numbers are drawn
// into a WebGL scene, so "are they on screen" is a question about pixels,
// and "did the download follow" is a question about the bytes that reached
// the browser. Per CLAUDE.md, page.screenshot() cannot capture WebGL, so
// every visual check below is canvas.toDataURL() through page.evaluate(),
// and the download checks read the actual saved file rather than trusting
// that the capture path shares the scene.
//
// The shape of every visual assertion is the same, and it is deliberate:
// snapshot the canvas with the numbers ON, flip the switch, snapshot again,
// and require the two to differ. A viewer drawing no labels at all would
// produce two identical images and fail, which is what makes this a real
// check rather than a check that clicking a button re-renders something.
//
// Two of the checks exist for one specific regression. MoCubeViewer and
// ModeAnimationViewer both rebuild their whole scene with `clear()`, which
// wipes labels: MoCubeViewer on every tick of the isovalue slider,
// ModeAnimationViewer on every change of vibrational mode. If the effect
// that re-draws the labels is not keyed on those inputs, the numbers vanish
// the first time anybody touches either control and never come back. Both
// controls are therefore driven here, with the numbers on, before the
// on-versus-off comparison is taken.
//
// Self-contained on the opt_02 pattern: its own user, its own thread, its
// own seeded jobs, and it deletes both the jobs and the account (and with
// it the thread) at the end. It never purges anything it did not create.
//
// Run against the docker-compose dev stack, with frontend/dist REBUILT
// (nginx serves dist from a host bind mount):
//
//   npm --prefix frontend run build
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/ui_10_atom_label_toggle.spec.mjs
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_ui10_" + Math.random().toString(36).slice(2, 8);

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 300000,
  }).trim();
}

/** toDataURL() of the last currently-visible <canvas> in the page -- the
 *  3Dmol viewers each own exactly one, and the most recently mounted is the
 *  one a just-opened drawer put there. Returns null rather than throwing if
 *  the read is refused, so a failure reports as a mismatch with a reason
 *  instead of killing the run. */
async function canvasSnapshot(page) {
  return page.evaluate(() => {
    const canvases = Array.from(document.querySelectorAll("canvas")).filter((c) => c.offsetParent !== null);
    const c = canvases[canvases.length - 1];
    if (!c) return null;
    try {
      return c.toDataURL();
    } catch {
      return null;
    }
  });
}

/** Flip the switch and wait for the re-render to land. The viewers render
 *  synchronously inside a React effect, so one animation frame plus a small
 *  settle is enough; this is not polling for an async fetch. */
async function toggle(page, testId) {
  await page.click(`[data-testid="${testId}"]`);
  await page.waitForTimeout(400);
}

/** Clicks a download control and returns { name, bytes } of what the
 *  browser actually saved. The app hands downloads over as an <a download>
 *  on a blob URL (frontend/src/lib/download.ts), so this is a real download
 *  event and not an interception of the data URI on the way past. */
async function captureDownload(page, testId, timeout = 40000) {
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout }),
    page.click(`[data-testid="${testId}"]`),
  ]);
  const file = await download.path();
  return { name: download.suggestedFilename(), bytes: readFileSync(file) };
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_ui10_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  // acceptDownloads is Playwright's default, so the shared helper's context
  // is enough -- the download checks below need no special setup.
  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  // Kept alongside the console log because a failing request is the usual
  // reason a drawer closes underneath this spec.
  const badResponses = [];
  page.on("response", (r) => {
    if (r.status() >= 400) badResponses.push(`${r.status()} ${r.request().method()} ${r.url()}`);
  });

  // Visible to the finally block, which must clean up whatever got as far as
  // being created even if the run threw before the checks.
  const seededJobIds = { freq: null, gs: null };
  let seededThreadId = null;

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
    // The app probes /api/auth/me on load, before anyone is logged in, and
    // that probe legitimately answers 401. It is not a fault and it is not
    // what this spec is watching for, so the error log starts from here.
    consoleErrors.length = 0;
    badResponses.length = 0;

    const usersRes = await adminCtx.request.get(`${BASE_URL}/api/admin/users`);
    const user = (await usersRes.json()).find((u) => u.username === username);
    check("found the just-registered user via the admin API", !!user, username);

    console.log("\n== seed a thread with a molecule, a freq job and a ground-state job ==");
    // Water at HF/STO-3G on PySCF for both: it is the cheapest thing that
    // still produces real normal modes (for the animation viewer) and real
    // orbitals (for the cube viewer), and this spec is about the labels
    // drawn over the atoms, not about the chemistry.
    const seedCode = `
import json, time
from app.agent import threads as thread_registry
from app.agent.graph import add_geometry_frames
from app.auth.models import record_ownership
from app.chemistry.jobs.base import JobSpec, get_job_manager
from server.routes.chat import _config

USER_ID = "${user.id}"
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}

thread = thread_registry.create_thread(label="${THREAD_LABEL}")
thread_id = thread["thread_id"]
record_ownership("thread", thread_id, USER_ID)
add_geometry_frames(_config(thread_id), [WATER])

mgr = get_job_manager()
freq_job_id = mgr.submit(
    JobSpec(task="freq", subtype="", method="hf", engine="pyscf", molecule=WATER,
            params={"basis": "sto-3g"}),
    owner_user_id=USER_ID,
)
gs_job_id = mgr.submit(
    JobSpec(task="single_point", subtype="gs", method="hf", engine="pyscf", molecule=WATER,
            params={"basis": "sto-3g"}),
    owner_user_id=USER_ID,
)
# Deliberately NOT set_active_job_ids: attaching the jobs to the thread makes
# the agent run a 'these finished, summarise them' turn, and that turn landing
# mid-run re-renders the thread and closes an open job drawer. The jobs are
# still reachable from the Job Manager panel, which is where this spec opens
# them from.

deadline = time.time() + 300
statuses = {}
while time.time() < deadline:
    statuses = {
        "freq": (mgr.status(freq_job_id) or {}).get("status"),
        "gs": (mgr.status(gs_job_id) or {}).get("status"),
    }
    if all(s in ("completed", "failed", "cancelled") for s in statuses.values()):
        break
    time.sleep(1.0)

print(json.dumps({"thread_id": thread_id, "freq_job_id": freq_job_id, "gs_job_id": gs_job_id, **statuses}))
`;
    const seeded = JSON.parse(execApi(seedCode).trim().split("\n").pop());
    console.log(`seeded: ${JSON.stringify(seeded)}`);
    seededJobIds.freq = seeded.freq_job_id;
    seededJobIds.gs = seeded.gs_job_id;
    seededThreadId = seeded.thread_id;
    check("the seeded frequency job completed", seeded.freq === "completed", seeded.freq);
    check("the seeded ground-state job completed", seeded.gs === "completed", seeded.gs);

    console.log("\n== open the thread ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(`[data-testid="jobmanager-row-${seeded.freq_job_id}"]`, { timeout: 30000 });

    // ---- 1. the control renders where it was asked to live -------------
    console.log("\n== the switch renders in the molecule pane ==");
    await page.waitForSelector('[data-testid="molecule-atom-labels"]', { timeout: 15000 });
    const paneToggle = page.locator('[data-testid="molecule-atom-labels"]');
    check("the atom-number switch renders in the molecule pane", await paneToggle.isVisible());
    check(
      "it reports itself as a switch that is on by default",
      (await paneToggle.getAttribute("role")) === "switch" &&
        (await paneToggle.getAttribute("aria-checked")) === "true",
      `role=${await paneToggle.getAttribute("role")} aria-checked=${await paneToggle.getAttribute("aria-checked")}`,
    );

    // ---- 2. it changes what the molecule viewer draws -------------------
    console.log("\n== flipping it changes what the molecule pane draws ==");
    await page.waitForTimeout(1200); // let the viewer mount and frame
    const molOn = await canvasSnapshot(page);
    check("captured the molecule viewer with numbers on", !!molOn);
    await toggle(page, "molecule-atom-labels");
    const molOff = await canvasSnapshot(page);
    check(
      "turning the numbers off changes the molecule viewer's pixels",
      !!molOff && molOff !== molOn,
      molOff === molOn ? "the canvas was byte-identical, so no labels were removed" : "canvas differed",
    );
    check(
      "the switch now reports itself as off",
      (await paneToggle.getAttribute("aria-checked")) === "false",
    );

    // ---- 3. the download follows the switch ----------------------------
    // The point of the whole feature: what is exported has to match what is
    // on screen. Compared as bytes, from the file the browser saved.
    console.log("\n== the exported PNG follows the switch ==");
    const pngOff = await captureDownload(page, "viewer-download-png");
    await toggle(page, "molecule-atom-labels");
    const molBackOn = await canvasSnapshot(page);
    check(
      "turning them back on restores the numbers",
      !!molBackOn && molBackOn !== molOff,
      molBackOn === molOff ? "the canvas did not change back" : "canvas differed",
    );
    const pngOn = await captureDownload(page, "viewer-download-png");
    check(
      "the downloaded PNG differs with the numbers on and off",
      !pngOn.bytes.equals(pngOff.bytes),
      `on=${pngOn.bytes.length}B off=${pngOff.bytes.length}B, name=${pngOn.name}`,
    );

    // ---- 4. the orbital viewer, including across an isovalue drag ------
    console.log("\n== the orbital viewer obeys it, and keeps the numbers across an isovalue drag ==");
    // The job row, by testid. NOT `text=<job id>`: the agent's own summary
    // of these jobs names both ids in the chat transcript, so a text match
    // lands on a paragraph and silently opens nothing.
    await page.click(`[data-testid="jobmanager-row-${seeded.gs_job_id}"]`);
    await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
    await page.waitForSelector('[data-testid^="orbital-row-"]', { timeout: 20000 });
    await page.locator('[data-testid^="orbital-row-"]').first().click();
    await page.waitForSelector('[data-testid="mocube-atom-labels"]', { timeout: 60000 });
    check("the switch renders in the orbital viewer's overlay", true);
    await page.waitForTimeout(1500);

    // Drag the isovalue BEFORE comparing. This is the rebuild that used to
    // take the labels with it. Driven through React's own value setter and a
    // dispatched input event rather than fill(): a range input has no text to
    // fill, and this is what a real drag delivers to the onChange handler.
    const isoval = page.locator('[data-testid="mocube-isoval"]');
    await isoval.evaluate((el) => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      setter.call(el, "0.08");
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForTimeout(2000);
    console.log(
      `  after the isovalue drag: dialogs=${await page.locator('[role="dialog"]').count()}` +
        ` toggles=${await page.locator('[data-testid="mocube-atom-labels"]').count()}`,
    );

    const cubeOn = await canvasSnapshot(page);
    await toggle(page, "mocube-atom-labels");
    await page.waitForTimeout(400);
    const cubeOff = await canvasSnapshot(page);
    check(
      "the numbers are still drawn on the orbital after an isovalue drag, and come off with the switch",
      !!cubeOn && !!cubeOff && cubeOn !== cubeOff,
      cubeOn === cubeOff
        ? "identical before/after the switch, i.e. the isovalue drag had already wiped the labels"
        : "canvas differed",
    );
    // Leave it off, so the next drawer inherits an off state and the
    // persistence check at the end has something non-default to prove.
    await page.keyboard.press("Escape");
    await page.waitForTimeout(600);

    // ---- 5. the vibration viewer, including across a mode change -------
    console.log("\n== the vibration viewer obeys it, and keeps the numbers across a mode change ==");
    await page.click(`[data-testid="jobmanager-row-${seeded.freq_job_id}"]`);
    await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
    await page.waitForSelector('[data-testid^="vibration-row-"]', { timeout: 20000 });
    await page.locator('[data-testid^="vibration-row-"]').first().click();
    await page.waitForSelector('[data-testid="mode-atom-labels"]', { timeout: 20000 });
    check("the switch renders in the vibration viewer's overlay", true);
    check(
      "the state set in the instrument panel is already in force in the drawer",
      (await page.locator('[data-testid="mode-atom-labels"]').getAttribute("aria-checked")) === "false",
    );

    // With the numbers OFF, capture the animation. This is the one download
    // that can hang rather than fail: captureApng resolves only once the
    // viewer has rendered its frame quota, so a broken label path that
    // stalls rendering shows up here as a timeout.
    const apngOff = await captureDownload(page, "mode-download-apng", 60000);
    check(
      "an animated PNG still exports with the numbers off",
      apngOff.bytes.length > 1000,
      `${apngOff.bytes.length}B, name=${apngOff.name}`,
    );

    // Turn them back on, then change mode -- the rebuild that used to wipe
    // them -- and only then compare on against off.
    await toggle(page, "mode-atom-labels");
    const modeRows = page.locator('[data-testid^="vibration-row-"]');
    if ((await modeRows.count()) > 1) {
      await modeRows.nth(1).click();
      await page.waitForTimeout(1200);
    }
    const modeOn = await canvasSnapshot(page);
    await toggle(page, "mode-atom-labels");
    const modeOff = await canvasSnapshot(page);
    check(
      "the numbers are still drawn on the vibration after a mode change, and come off with the switch",
      !!modeOn && !!modeOff && modeOn !== modeOff,
      modeOn === modeOff
        ? "identical before/after the switch, i.e. the mode change had already wiped the labels"
        : "canvas differed",
    );
    await page.keyboard.press("Escape");

    // ---- 6. the preference survives a reload ---------------------------
    console.log("\n== the preference survives a reload ==");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="molecule-atom-labels"]', { timeout: 20000 });
    check(
      "the switch is still off after a reload",
      (await page.locator('[data-testid="molecule-atom-labels"]').getAttribute("aria-checked")) === "false",
    );

    check(
      "no console errors during the run",
      consoleErrors.length === 0,
      [...consoleErrors.slice(0, 3), ...badResponses.slice(0, 3)].join(" | ").slice(0, 400),
    );
  } catch (e) {
    check("spec ran without throwing", false, String(e?.stack ?? e).slice(0, 500));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    try {
      // The seeded jobs go first, and explicitly: they are submitted through
      // the job manager rather than created by this user in the UI, so
      // deleting the account does not take them with it, and a suite run
      // must not leave jobs sitting in everyone's job list.
      const cleanupPage = await adminCtx.newPage();
      for (const jobId of [seededJobIds.freq, seededJobIds.gs]) {
        if (!jobId) continue;
        try {
          await cleanupPage.request.delete(`${BASE_URL}/api/jobs/${jobId}`, {
            headers: { Origin: BASE_URL }, timeout: 60000,
          });
        } catch (e) {
          console.log(`  (cleanup) failed to delete job ${jobId}: ${String(e).slice(0, 200)}`);
        }
      }
      // The thread goes explicitly. Deleting the account does NOT take its
      // conversations with it -- verified by finding ten of these left on the
      // stack after this spec's own development runs -- and a conversation
      // list slowly filling with qatest_* entries is exactly the litter the
      // suite is supposed to avoid.
      if (seededThreadId) {
        try {
          await cleanupPage.request.delete(`${BASE_URL}/api/threads/${seededThreadId}`, {
            headers: { Origin: BASE_URL }, timeout: 60000,
          });
        } catch (e) {
          console.log(`  (cleanup) failed to delete thread ${seededThreadId}: ${String(e).slice(0, 200)}`);
        }
      }
      const found = (await (await cleanupPage.request.get(`${BASE_URL}/api/admin/users`)).json())
        .find((u) => u.username === username);
      if (found) {
        await cleanupPage.request.delete(`${BASE_URL}/api/admin/users/${found.id}`, { timeout: 180000 });
      }
      await cleanupPage.close();
    } catch (e) {
      console.log(`  (cleanup) failed to delete test user ${username}: ${String(e).slice(0, 200)}`);
    }
    await browser.close();
  }

  process.exit(summary() ? 0 : 1);
}

main();
