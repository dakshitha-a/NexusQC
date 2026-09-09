// Two visual fixes, both of which a code read would happily lie about
// because they are questions about boxes, not about markup:
//
//  1. A long job name used to widen the job-list table past its panel, so
//     the panel grew a horizontal scrollbar and the row's cancel/delete
//     button sat off-screen until you scrolled to it. The name now fades out
//     where it runs out of room and the button stays put.
//  2. The download and expand buttons for the orbital and vibrational-mode
//     viewers floated in the PANEL's top-right corner, which for those two
//     panels is over the orbital dropdown / the frequency table rather than
//     over the viewer they act on. They now sit in the viewer's own corner.
//
// Both are asserted with getBoundingClientRect, not screenshots -- no canvas
// pixels are involved, so the toDataURL trap in CLAUDE.md doesn't apply here.
//
// Self-contained on the opt_02 pattern: its own user, its own thread, its own
// seeded jobs, and it deletes the user (and with them the jobs) at the end.
//
// Run against the docker-compose dev stack, with frontend/dist REBUILT
// (nginx serves dist from a host bind mount):
//
//   npm --prefix frontend run build
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/ui_06_row_and_viewer_controls.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_ui06_" + Math.random().toString(36).slice(2, 8);
// Long enough that no plausible panel width can fit it, and unbroken so no
// wrapping opportunity exists -- this is exactly the shape that used to set
// the table's minimum width.
const LONG_LABEL =
  "excited state scan of a very long molecule name that nobody would sensibly type but everybody eventually does 0123456789";

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 300000,
  }).trim();
}

/** True when `inner` sits inside `outer` with a small tolerance, i.e. the
 *  control is really over the box it belongs to and not merely near it. */
/** Both axes, so a failure says which one gave. The two panel-containment
 *  checks below used to print only the horizontal bounds, which made a
 *  vertical failure read as a passing measurement next to a FAIL. */
function describeContainment(outer, inner) {
  const r = (n) => Math.round(n);
  return (
    `x: button ${r(inner.left)}-${r(inner.right)} in panel ${r(outer.left)}-${r(outer.right)}; ` +
    `y: button ${r(inner.top)}-${r(inner.bottom)} in panel ${r(outer.top)}-${r(outer.bottom)}`
  );
}

/** Measures a control against the scroll container it lives in, having
 *  first scrolled it into view.
 *
 *  The scroll matters. These panels scroll vertically by design, so on a
 *  deployment carrying enough jobs the seeded row sits below the fold and
 *  the control is legitimately outside its container's box -- which says
 *  nothing at all about the horizontal-overflow fault these checks exist
 *  to catch (a button pushed behind a horizontal scrollbar by a long job
 *  name; see JobManagerPanel's own table-fixed comment). Without this the
 *  result depended on how many jobs happened to be on the stack. */
async function measureInPanel(page, selector) {
  await page.locator(selector).scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  return page.evaluate((sel) => {
    const btn = document.querySelector(sel);
    const scroller = btn.closest(".overflow-y-auto");
    const s = scroller.getBoundingClientRect();
    const b = btn.getBoundingClientRect();
    return {
      scrollWidth: scroller.scrollWidth,
      clientWidth: scroller.clientWidth,
      rect: { left: s.left, right: s.right, top: s.top, bottom: s.bottom },
      button: { left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width, height: b.height },
    };
  }, selector);
}

function contains(outer, inner, slack = 2) {
  return (
    inner.left >= outer.left - slack &&
    inner.right <= outer.right + slack &&
    inner.top >= outer.top - slack &&
    inner.bottom <= outer.bottom + slack
  );
}

const rectOf = (page, selector) =>
  page.$eval(selector, (el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
  });

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_ui06_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

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

    const usersRes = await adminCtx.request.get(`${BASE_URL}/api/admin/users`);
    const user = (await usersRes.json()).find((u) => u.username === username);
    check("found the just-registered user via the admin API", !!user, username);

    console.log("\n== seed a completed frequency job with an absurdly long label ==");
    const seedCode = `
import json, time
from app.agent import threads as thread_registry
from app.auth.models import record_ownership
from app.chemistry.jobs.base import JobSpec, get_job_manager, write_meta

USER_ID = "${user.id}"
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}

thread = thread_registry.create_thread(label="${THREAD_LABEL}")
thread_id = thread["thread_id"]
record_ownership("thread", thread_id, USER_ID)

mgr = get_job_manager()
freq_job_id = mgr.submit(
    JobSpec(task="freq", method="hf", engine="orca", molecule=WATER,
            params={"basis": "sto-3g"}),
    owner_user_id=USER_ID,
)
# The display label is the mutable one in meta.json, which is what a rename
# writes and what both job lists render -- JobSpec.label is only a seed for it.
write_meta(freq_job_id, {"label": ${JSON.stringify(LONG_LABEL)}})
sp_job_id = mgr.submit(
    JobSpec(task="single_point", method="hf", engine="orca", molecule=WATER,
            params={"basis": "sto-3g"}),
    owner_user_id=USER_ID,
)
thread_registry.set_active_job_ids(thread_id, [freq_job_id, sp_job_id])

deadline = time.time() + 280
statuses = {}
while time.time() < deadline:
    statuses = {"freq": (mgr.status(freq_job_id) or {}).get("status"),
                "sp": (mgr.status(sp_job_id) or {}).get("status")}
    if all(s in ("completed", "failed", "cancelled") for s in statuses.values()):
        break
    time.sleep(1.0)

print(json.dumps({"thread_id": thread_id, "freq_job_id": freq_job_id, "sp_job_id": sp_job_id, **statuses}))
`;
    const seeded = JSON.parse(execApi(seedCode).trim().split("\n").pop());
    console.log(`seeded: ${JSON.stringify(seeded)}`);
    check("the seeded frequency job reached status=completed", seeded.freq === "completed", seeded.freq);
    check("the seeded single-point job reached status=completed", seeded.sp === "completed", seeded.sp);

    console.log("\n== the conversation's job list: long name, button still in view ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    const killSel = `[data-testid="job-kill-${seeded.freq_job_id}"]`;
    await page.waitForSelector(killSel, { timeout: 30000 });

    const listBox = await measureInPanel(page, killSel);
    check("the job list does not scroll sideways despite the long name",
      listBox.scrollWidth <= listBox.clientWidth + 1,
      `scrollWidth=${listBox.scrollWidth} clientWidth=${listBox.clientWidth}`);

    const killRect = listBox.button;
    check("the cancel button is inside the panel without scrolling",
      contains(listBox.rect, killRect),
      describeContainment(listBox.rect, killRect));
    check("the cancel button is not clipped to nothing",
      killRect.width >= 16 && killRect.height >= 16,
      `${Math.round(killRect.width)}x${Math.round(killRect.height)}`);

    const nameFade = await page.evaluate((sel) => {
      const row = document.querySelector(sel).closest("tr");
      const nameCell = row.querySelector("td[title]");
      const line = nameCell.querySelector("div");
      return {
        title: nameCell.getAttribute("title"),
        mask: getComputedStyle(line).maskImage || getComputedStyle(line).webkitMaskImage,
        textOverflow: getComputedStyle(line).textOverflow,
        overflows: line.scrollWidth > line.clientWidth,
      };
    }, killSel);
    check("the full name is available as a hover tooltip",
      (nameFade.title || "").includes("nobody would sensibly type"), (nameFade.title || "").slice(0, 40) + "...");
    check("the name really is cut off (so the fade is doing something)", nameFade.overflows);
    check("the cut-off name fades rather than ending in an ellipsis",
      /gradient/.test(nameFade.mask) && nameFade.textOverflow !== "ellipsis",
      `mask=${String(nameFade.mask).slice(0, 40)} textOverflow=${nameFade.textOverflow}`);

    console.log("\n== the Job Manager list: same, with the delete button ==");
    // Both lists live in the right dock at once -- the conversation's own
    // above, the cross-conversation Job Manager below -- so there is nothing
    // to navigate to here.
    const delSel = `[data-testid="job-delete-${seeded.freq_job_id}"]`;
    await page.waitForSelector(delSel, { timeout: 15000 });
    const mgrBox = await measureInPanel(page, delSel);
    check("the Job Manager list does not scroll sideways either",
      mgrBox.scrollWidth <= mgrBox.clientWidth + 1,
      `scrollWidth=${mgrBox.scrollWidth} clientWidth=${mgrBox.clientWidth}`);
    const delRect = mgrBox.button;
    check("the delete button is inside the Job Manager panel without scrolling",
      contains(mgrBox.rect, delRect),
      describeContainment(mgrBox.rect, delRect));

    console.log("\n== the vibrational-mode viewer owns its own corner ==");
    // Addressed by testid, not by cell position: the relative time used to
    // be a column of its own here, so td:nth-child(4) was the time cell and
    // is now the action cell, which stops click propagation. That change
    // would have shown up as a timeout on the panel selector below rather
    // than as anything naming the real cause.
    await page.click(`[data-testid="jobmanager-name-${seeded.freq_job_id}"]`);
    await page.waitForSelector('[data-panel="vibrations"]', { timeout: 20000 });
    const modeRow = '[data-panel="vibrations"] tbody tr';
    await page.waitForSelector(modeRow, { timeout: 15000 });
    await page.click(`${modeRow} >> nth=2`);
    await page.waitForSelector('[data-testid="mode-download-apng"]', { timeout: 20000 });
    await page.waitForTimeout(400);

    for (const state of ["collapsed", "expanded"]) {
      if (state === "expanded") {
        await page.click('[data-panel="vibrations"] [data-testid="panel-expand"]');
        await page.waitForTimeout(600);
      }
      const viewerBox = await page.$eval('[data-testid="mode-download-apng"]', (btn) => {
        // The viewer box is the positioned box the control row is anchored in.
        const anchor = btn.closest("span.absolute");
        const r = anchor.parentElement.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
      });
      const dl = await rectOf(page, '[data-testid="mode-download-apng"]');
      const exp = await rectOf(page, '[data-panel="vibrations"] [data-testid="panel-expand"]');
      check(`${state}: the mode viewer's download button sits inside the viewer box`,
        contains(viewerBox, dl),
        `btn top=${Math.round(dl.top)} box top=${Math.round(viewerBox.top)} h=${Math.round(viewerBox.height)}`);
      check(`${state}: the expand toggle sits inside the same viewer box`,
        contains(viewerBox, exp),
        `btn right=${Math.round(exp.right)} box right=${Math.round(viewerBox.right)}`);
      check(`${state}: the two buttons are side by side, not stacked on each other`,
        Math.abs(dl.top - exp.top) < 6 && dl.right <= exp.left + 2,
        `download right=${Math.round(dl.right)} expand left=${Math.round(exp.left)}`);
    }
    await page.click('[data-panel="vibrations"] [data-testid="panel-expand"]');
    await page.waitForTimeout(400);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);

    console.log("\n== the orbital viewer owns its own corner ==");
    await page.click(`[data-testid="jobmanager-name-${seeded.sp_job_id}"]`);
    await page.waitForSelector('[data-panel="orbitals"]', { timeout: 20000 });
    await page.click('[data-panel="orbitals"] tbody tr >> nth=0');
    // The cube is rendered lazily server-side (orca_plot), so the download
    // button only appears once there is something to download.
    await page.waitForSelector('[data-testid="mocube-download-png"]', { timeout: 90000 });
    await page.waitForTimeout(400);
    const cubeBox = await page.$eval('[data-testid="mocube-download-png"]', (btn) => {
      const r = btn.closest("span.absolute").parentElement.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
    });
    const cubeDl = await rectOf(page, '[data-testid="mocube-download-png"]');
    const cubeExp = await rectOf(page, '[data-panel="orbitals"] [data-testid="panel-expand"]');
    check("the orbital viewer's download button sits inside the isosurface box",
      contains(cubeBox, cubeDl),
      `btn top=${Math.round(cubeDl.top)} box top=${Math.round(cubeBox.top)}`);
    check("the expand toggle moved down into that box too, off the orbital dropdown",
      contains(cubeBox, cubeExp),
      `btn top=${Math.round(cubeExp.top)} box=${Math.round(cubeBox.top)}-${Math.round(cubeBox.bottom)}`);

    console.log("\n== no console errors ==");
    const real = consoleErrors.filter((t) => !/status of 401/i.test(t) && !/favicon/i.test(t));
    check("no console errors beyond the known environmental ones",
      real.length === 0, real.slice(0, 3).join(" | "));
  } catch (e) {
    check("spec ran without throwing", false, String(e?.stack ?? e).slice(0, 500));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    // Deleting the user removes the jobs seeded above with them, so a run
    // leaves the job list as it found it.
    try {
      const cleanupPage = await adminCtx.newPage();
      const res = await cleanupPage.request.get(`${BASE_URL}/api/admin/users`);
      const found = (await res.json()).find((u) => u.username === username);
      if (found) await cleanupPage.request.delete(`${BASE_URL}/api/admin/users/${found.id}`, { headers: { Origin: BASE_URL }, timeout: 180000 });
      await cleanupPage.close();
    } catch (e) {
      console.log(`  (cleanup) failed to delete test user ${username}: ${String(e).slice(0, 200)}`);
    }
    await browser.close();
  }

  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main();
