// Phase 6's Playwright drawer check: a completed opt/constrained and a
// completed opt/ci job render in a real browser against the live dev
// stack, not just as a code read.
//
// No new frontend code exists for this phase -- P2B.5 already keyed the
// optimization sections on `optimized_molecule` being present in the
// summary (not on subtype), and the generic Summary key/value table
// already renders whatever fields a runner writes. This spec exists to
// prove that claim empirically rather than trust it: opt/constrained and
// opt/ci write new summary fields (`constraints`, `optimization_type`,
// `ci_energy_diff_hartree`) that did not exist before Phase 6, and a
// silently-empty drawer looks identical to a working one in a code read.
//
// Self-contained on the fail_01_notice_card.spec.mjs / grad_02 pattern:
// its own user, its own thread, its own seeded jobs via `docker compose
// exec api python -c ...`.
//
// Run against the real docker-compose dev stack (needs a rebuilt
// frontend/dist only if frontend code changed -- it did not this phase):
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/opt_02_optimization_drawer.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_opt02_" + Math.random().toString(36).slice(2, 8);

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 220000,
  }).trim();
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_opt02_" + Math.random().toString(36).slice(2, 8);
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

    console.log("\n== look up this user's id, for ownership recording ==");
    const usersRes = await adminCtx.request.get(`${BASE_URL}/api/admin/users`);
    const users = await usersRes.json();
    const user = users.find((u) => u.username === username);
    check("found the just-registered user via the admin API", !!user, username);

    console.log("\n== seed a real completed opt/constrained and opt/ci job, owned by this user ==");
    const seedCode = `
import json, time
from app.agent import threads as thread_registry
from app.auth.models import record_ownership
from app.chemistry.jobs.base import JobSpec, get_job_manager

USER_ID = "${user.id}"
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
ETHYLENE = {"name": "ethylene", "symbols": ["C", "C", "H", "H", "H", "H"],
            "coords": [[0.595560237, -0.010483480, -0.000284187],
                       [-0.831313750, 0.167231832, 0.001482505],
                       [-1.381857976, 0.227877089, 0.963419721],
                       [1.265119434, 0.874806815, 0.006897459],
                       [-1.382258208, 0.243775568, -0.959090898],
                       [1.027489724, -1.032962768, -0.008829646]],
            "charge": 0, "multiplicity": 1}

thread = thread_registry.create_thread(label="${THREAD_LABEL}")
thread_id = thread["thread_id"]
record_ownership("thread", thread_id, USER_ID)

mgr = get_job_manager()
constr_job_id = mgr.submit(
    JobSpec(task="opt", subtype="constrained", method="hf", engine="pyscf", molecule=WATER,
            params={"basis": "sto-3g", "constraints": [{"type": "bond", "atoms": [1, 2], "value": 0.98}]}),
    owner_user_id=USER_ID,
)
ci_job_id = mgr.submit(
    JobSpec(task="opt", subtype="ci", method="hf", engine="orca", molecule=ETHYLENE,
            params={"basis": "sto-3g", "optimization_type": "conical_intersection",
                    "target_state_2": 1, "n_states": 2, "max_steps": 300}),
    owner_user_id=USER_ID,
)
thread_registry.set_active_job_ids(thread_id, [constr_job_id, ci_job_id])

deadline = time.time() + 300
statuses = {}
while time.time() < deadline:
    statuses = {
        "constr": (mgr.status(constr_job_id) or {}).get("status"),
        "ci": (mgr.status(ci_job_id) or {}).get("status"),
    }
    if all(s in ("completed", "failed", "cancelled") for s in statuses.values()):
        break
    time.sleep(1.0)

print(json.dumps({"thread_id": thread_id, "constr_job_id": constr_job_id, "ci_job_id": ci_job_id, **statuses}))
`;
    const seedOut = execApi(seedCode);
    const seeded = JSON.parse(seedOut.trim().split("\n").pop());
    console.log(`seeded: ${JSON.stringify(seeded)}`);
    check("the seeded constrained-opt job reached status=completed", seeded.constr === "completed", seeded.constr);
    check("the seeded CI-opt job reached status=completed", seeded.ci === "completed", seeded.ci);

    console.log("\n== open the thread ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(`text=${seeded.constr_job_id}`, { timeout: 30000 });

    console.log("\n== opt/constrained job: drawer shows the optimized geometry + constraints field ==");
    await page.click(`text=${seeded.constr_job_id}`);
    await page.waitForSelector("text=Optimized geometry", { timeout: 15000 });
    check("the drawer shows 'Optimized geometry' (not 'Input geometry')",
      await page.isVisible("text=Optimized geometry"));
    check("the Summary table shows the constraints field",
      await page.isVisible('[role="dialog"] >> text=constraints'));
    check("the Summary table shows final_energy_hartree",
      await page.isVisible('[role="dialog"] >> text=final_energy_hartree'));

    console.log("\n== opt/ci job: drawer shows the optimized geometry + CI fields ==");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    await page.click(`text=${seeded.ci_job_id}`);
    await page.waitForSelector("text=Optimized geometry", { timeout: 15000 });
    check("the drawer shows 'Optimized geometry' for the CI-opt job too",
      await page.isVisible("text=Optimized geometry"));
    check("the Summary table shows optimization_type",
      await page.isVisible('[role="dialog"] >> text=optimization_type'));
    check("the Summary table shows ci_energy_diff_hartree",
      await page.isVisible('[role="dialog"] >> text=ci_energy_diff_hartree'));

    console.log("\n== no console errors ==");
    const real = consoleErrors.filter(
      (t) => !/status of 401/i.test(t) && !/favicon/i.test(t),
    );
    check("no console errors beyond the known environmental ones",
      real.length === 0, real.slice(0, 3).join(" | "));
  } catch (e) {
    check("spec ran without throwing", false, String(e?.stack ?? e).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    try {
      const cleanupPage = await adminCtx.newPage();
      const usersRes = await cleanupPage.request.get(`${BASE_URL}/api/admin/users`);
      const found = (await usersRes.json()).find((u) => u.username === username);
      if (found) {
        await cleanupPage.request.delete(`${BASE_URL}/api/admin/users/${found.id}`, { timeout: 180000 });
      }
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
