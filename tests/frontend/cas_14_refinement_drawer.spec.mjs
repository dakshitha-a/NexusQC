// The CAS refinement drawer, in a real browser.
//
// The backlog carried this as "the drawer has never been opened in a browser",
// on the understanding that the rendering existed and only lacked a check.
// It did not exist. The dedicated "Active-space recommendation" section in
// JobDetailDrawer.tsx draws the recommendation's own fields -- the tiers, the
// orbital indices, the state table, the verification -- and the refinement's
// outputs were not in its exclusion list either, so `rotations`,
// `natural_occupations`, `state_characters` and `orbital_characters` fell
// through to the generic key/value dump. A rotation trail rendered there is a
// list of objects and an occupation list is a bare row of numbers with nothing
// saying which orbital each belongs to. Searching every branch for that code
// finds nothing: it was never written.
//
// So this spec covers new rendering rather than confirming old rendering, and
// the two things it has to prove are the two the method document is emphatic
// about. The occupations and characters describe the NATURAL orbitals rather
// than the restart orbitals in orbitals.molden, and the rotation trail's
// indices are 1-based against that same natural set. Pairing either with the
// wrong file is the documented trap, so the drawer has to say which set it
// means, in the browser, where a silently missing caption looks identical to a
// present one in a code read.
//
// Self-contained on the opt_02 pattern: its own user, its own thread, its own
// seeded jobs, all deleted afterwards.
//
// Needs a rebuilt frontend/dist, because nginx serves it from a host bind
// mount and `docker compose build` will not refresh it:
//
//   cd frontend && npm run build
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/cas_14_refinement_drawer.spec.mjs
//
// QC_AGENT_COMPOSE_DIR overrides where the compose files are looked for, which
// a git worktree needs: docker-compose.override.yml is machine-specific and
// untracked, so it exists only in the primary checkout.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = process.env.QC_AGENT_COMPOSE_DIR
  || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_cas14_" + Math.random().toString(36).slice(2, 8);

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 600000,
  }).trim();
}

/**
 * Resolves once the job detail drawer has actually painted its job, not merely
 * once the dialog element exists. See R-099: the two are seconds apart on a
 * loaded host, and treating them as one event makes every assertion that
 * follows a race against a fetch.
 */
async function drawerLoaded(page, timeout = 30000) {
  await page.waitForFunction(
    () => {
      const d = document.querySelector('[role="dialog"]');
      return !!d && !/^\s*Loading\.\.\./.test(d.textContent || "");
    },
    undefined,
    { timeout },
  );
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_cas14_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  const seeded = { rec: null, refine: null, thread: null, userId: null };

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
    const users = await usersRes.json();
    const user = users.find((u) => u.username === username);
    check("found the just-registered user", !!user, username);
    seeded.userId = user.id;

    console.log("\n== seed a real recommendation, then a real refinement of it ==");
    // Water, because its refinement genuinely does something: the recommended
    // (8e,6o) prunes to (4e,4o) at natural occupations of 1.9994 and 1.9990,
    // so the rotation trail has real prune entries to draw rather than being
    // empty, which is the case a test could pass without proving anything.
    const seedCode = `
import json, time
from app.agent import threads as thread_registry
from app.auth.models import record_ownership
from app.chemistry.jobs.base import JobSpec, get_job_manager

USER_ID = "${user.id}"
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}

thread = thread_registry.create_thread(label="${THREAD_LABEL}")
thread_id = thread["thread_id"]
record_ownership("thread", thread_id, USER_ID)
mgr = get_job_manager()

def wait(job_id, limit=420):
    deadline = time.time() + limit
    while time.time() < deadline:
        s = (mgr.status(job_id) or {}).get("status")
        if s in ("completed", "failed", "cancelled"):
            return s
        time.sleep(1.0)
    return "timeout"

rec_id = mgr.submit(
    JobSpec(task="cas_reco", subtype="", method="casscf", engine="pyscf",
            molecule=WATER, params={"n_states": 1}),
    owner_user_id=USER_ID,
)
rec_status = wait(rec_id)

ref_id = mgr.submit(
    JobSpec(task="cas_reco", subtype="refine", method="casscf", engine="pyscf",
            molecule=WATER,
            params={"n_states": 1, "active_space_source_job_id": rec_id}),
    owner_user_id=USER_ID,
)
ref_status = wait(ref_id)

thread_registry.set_active_job_ids(thread_id, [rec_id, ref_id])
summary = (mgr.status(ref_id) or {}).get("summary") or {}
print(json.dumps({"thread_id": thread_id, "rec_id": rec_id, "ref_id": ref_id,
                  "rec": rec_status, "ref": ref_status,
                  "keys": sorted(summary.keys())}))
`;
    const out = execApi(seedCode);
    const s = JSON.parse(out.trim().split("\n").pop());
    console.log(`seeded: ${s.rec_id} (${s.rec}) / ${s.ref_id} (${s.ref})`);
    seeded.rec = s.rec_id;
    seeded.refine = s.ref_id;
    seeded.thread = s.thread_id;
    check("the recommendation job completed", s.rec === "completed", s.rec);
    check("the refinement job completed", s.ref === "completed", s.ref);
    // Printed rather than asserted: `mgr.status()` does not necessarily carry
    // the summary, so an empty list here means nothing either way. What the
    // fields actually are is settled in the browser below, which is the only
    // place that can tell a missing field from an unrendered one.
    console.log(`summary keys seen from status(): ${s.keys.join(", ") || "(none)"}`);

    console.log("\n== open the refinement job's drawer ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(`text=${seeded.refine}`, { timeout: 30000 });
    // The job list renders the id in more than one place, and the row is what
    // opens the drawer. Click the last match, which is the row rather than any
    // header or notice mentioning the same id, and give the drawer room: it
    // fetches the job before it paints.
    const jobRow = page.locator(`text=${seeded.refine}`).last();
    await jobRow.scrollIntoViewIfNeeded();
    await jobRow.click();
    try {
      await page.waitForSelector('[role="dialog"]', { timeout: 30000 });
    } catch (e) {
      const body = (await page.locator("body").innerText()).slice(0, 900);
      console.log(`drawer did not open. Visible text was:\n${body}`);
      throw e;
    }
    // R-099. The dialog element is NOT the same event as the job data
    // arriving. JobDetailDrawer renders Dialog.Content unconditionally and
    // puts "Loading..." inside it until useJobQuery resolves, so
    // waitForSelector('[role="dialog"]') returns while the drawer is still
    // empty. Every assertion below then raced a fetch.
    //
    // That is what the 2026-09 review recorded as an app defect: it saw the
    // first four content checks fail and everything checked later pass, which
    // is exactly the shape of a drawer that filled in partway through the
    // assertions rather than one missing a summary key. Waiting for the
    // loading state to clear is the fix, and `drawerLoaded` below is used
    // everywhere this spec opens a drawer so the same race cannot come back
    // one assertion at a time.
    await drawerLoaded(page);

    console.log("\n== the three sections that had no rendering at all ==");
    check("the refined space is stated, with what it came from",
      await page.isVisible('[role="dialog"] >> text=Refined against a CASSCF'));

    const orbTable = page.locator('[data-testid="cas-refine-orbitals"]');
    check("the natural-orbital occupation table renders",
      (await orbTable.count()) === 1);
    const orbRows = await orbTable.locator("tbody tr").count();
    check(`it has one row per active orbital (${orbRows} rows)`, orbRows > 0, String(orbRows));
    check("each row carries a character label",
      await page.isVisible('[data-testid="cas-refine-orbitals"] >> text=sigma'));
    check("and the continuous weights beside the label, never instead of it",
      /sigma \d\.\d\d/.test(await orbTable.innerText()),
      (await orbTable.innerText()).slice(0, 160));
    check("the table says which orbital set it describes",
      await page.isVisible('[role="dialog"] >> text=natural_orbitals.molden'));

    const rotTable = page.locator('[data-testid="cas-refine-rotations"]');
    check("the rotation trail renders", (await rotTable.count()) === 1);
    const rotRows = await rotTable.locator("tbody tr").count();
    check(`it has one row per change made (${rotRows} rows)`, rotRows > 0, String(rotRows));
    const rotText = await rotTable.innerText();
    check("each row says why, not just what", rotText.includes("occupation"),
      rotText.slice(0, 200));
    check("and names the orbital it acted on",
      /out \d+/.test(rotText), rotText.slice(0, 200));
    check("and the index convention is stated",
      await page.isVisible('[role="dialog"] >> text=1-based against the natural-orbital set'));

    console.log("\n== nothing is drawn twice ==");
    // Every key the new section draws is in the drawer's exclusion list, so it
    // must not also appear as a raw row in the generic Summary table.
    const dialogText = await page.locator('[role="dialog"]').innerText();
    check("the raw 'rotations' key does not also appear in the Summary table",
      !/\brotations\b\s*\n/.test(dialogText));
    // A plain 401 resource load is filtered out and is not this drawer's
    // doing: the shell probes an admin-only route on load and a non-admin user
    // gets a 401 for it on every page in the app, refinement drawer or not.
    // Asserting on it here would make this spec fail for a reason it does not
    // cover. Anything else is a real error in the new rendering.
    const realErrors = consoleErrors.filter((e) => !/status of 401/.test(e));
    check("no console errors while rendering the drawer",
      realErrors.length === 0, realErrors.slice(0, 3).join(" | "));

    console.log("\n== R-099: the loading state is not missing data ==");
    // The positive control for the wait added above. Everything so far shows
    // the drawer renders correctly when the fetch is quick; none of it shows
    // that the review's reading, four content checks failing while everything
    // later passed, is what a slow fetch produces. This delays the drawer's
    // own job request by three seconds and measures both moments: what an
    // assertion fired the instant the dialog appears would have seen, and what
    // is there once the drawer has painted.
    //
    // Nothing about the app is changed here. Only the arrival time of a
    // response the app was always waiting for.
    const slowPage = await ctx.newPage();
    await slowPage.route(`**/api/jobs/${seeded.refine}`, async (route) => {
      await new Promise((r) => setTimeout(r, 3000));
      await route.continue();
    });
    await slowPage.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await slowPage.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await slowPage.click(`text=${THREAD_LABEL}`);
    await slowPage.waitForSelector(`text=${seeded.refine}`, { timeout: 30000 });
    const slowRow = slowPage.locator(`text=${seeded.refine}`).last();
    await slowRow.scrollIntoViewIfNeeded();
    await slowRow.click();
    await slowPage.waitForSelector('[role="dialog"]', { timeout: 30000 });

    const atDialog = {
      refined: await slowPage.isVisible('[role="dialog"] >> text=Refined against a CASSCF'),
      table: await slowPage.locator('[data-testid="cas-refine-orbitals"]').count(),
      rotations: await slowPage.locator('[data-testid="cas-refine-rotations"]').count(),
    };
    console.log(`   the instant [role="dialog"] appears: refined-space=${atDialog.refined}, ` +
      `occupation tables=${atDialog.table}, rotation tables=${atDialog.rotations}`);
    check(
      "with the job request held for three seconds, the dialog element exists while the drawer " +
      "is still empty, which is the whole of R-099: an assertion fired here reads a loading " +
      "drawer as an app that published no data",
      atDialog.table === 0 && atDialog.rotations === 0 && !atDialog.refined,
      JSON.stringify(atDialog),
    );

    await drawerLoaded(slowPage);
    const afterLoad = {
      refined: await slowPage.isVisible('[role="dialog"] >> text=Refined against a CASSCF'),
      rows: await slowPage.locator('[data-testid="cas-refine-orbitals"] tbody tr').count(),
    };
    console.log(`   after waiting for the drawer to paint: refined-space=${afterLoad.refined}, ` +
      `occupation rows=${afterLoad.rows}`);
    check(
      "and waiting for the drawer to paint finds the same content as before, so the data was " +
      "never missing, only late",
      afterLoad.refined && afterLoad.rows > 0,
      JSON.stringify(afterLoad),
    );
  } finally {
    console.log("\n== clean up everything this spec created ==");
    const ids = [seeded.rec, seeded.refine].filter(Boolean);
    if (ids.length || seeded.thread) {
      try {
        // `mgr.delete` removes the job's record but leaves its directory on
        // disk, so deleting alone left two orbitals.molden-carrying trees
        // behind on every run. The rmtree is what makes this cleanup true.
        execApi(`
import os, shutil
from app.agent import threads as thread_registry
from app.chemistry.jobs.base import get_job_manager
from app.config import JOBS_DIR
mgr = get_job_manager()
for jid in ${JSON.stringify(ids)}:
    try:
        mgr.delete(jid)
    except Exception as exc:
        print("job delete failed", jid, exc)
    shutil.rmtree(os.path.join(str(JOBS_DIR), jid), ignore_errors=True)
try:
    thread_registry.delete_thread("${seeded.thread}")
except Exception as exc:
    print("thread delete failed", exc)
print("cleaned")
`);
        console.log("removed the seeded jobs and thread");
      } catch (e) {
        console.log(`cleanup of jobs/thread failed: ${e}`);
      }
    }
    if (seeded.userId) {
      try {
        await adminCtx.request.delete(`${BASE_URL}/api/admin/users/${seeded.userId}`);
        console.log("removed the test user");
      } catch (e) {
        console.log(`user cleanup failed: ${e}`);
      }
    }
    await browser.close();
  }
  return summary();
}

main().then((ok) => process.exit(ok ? 0 : 1)).catch((e) => {
  console.error(e);
  process.exit(1);
});
