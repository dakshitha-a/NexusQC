// Phase 5's Playwright drawer check: a completed single_point/grad and a
// completed single_point/nac job render their GradientSection/NacSection
// in a real browser against the live dev stack, not just as a code read.
//
// Self-contained on the fail_01_notice_card.spec.mjs pattern (P4.8): its
// own user, its own thread, its own seeded job via `docker compose exec
// api python -c ...` (the same technique tests/backend/perf_03/04/05 and
// fail_01 already use to reach into the live container's own JobManager),
// with ownership explicitly recorded so the browser's own GET /api/jobs
// (scoped to the logged-in user's threads) can see it.
//
// Both jobs are plain water/HF/STO-3G-scale (a ground-state gradient, and
// a CASSCF(4,4)/STO-3G NAC) -- fast enough to complete well inside the
// job-watcher's poll interval, so no long wait is needed the way fail_01's
// slower probe does.
//
// Run against the real docker-compose dev stack (needs a rebuilt
// frontend/dist -- nginx serves it from a host bind mount):
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/grad_02_gradient_nac_drawer.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_grad02_" + Math.random().toString(36).slice(2, 8);

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
  const username = "qatest_grad02_" + Math.random().toString(36).slice(2, 8);
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
    await page.fill('input[placeholder="Password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 15000 });
    check("registered and logged in", true);

    console.log("\n== look up this user's id, for ownership recording ==");
    const usersRes = await adminCtx.request.get(`${BASE_URL}/api/admin/users`);
    const users = await usersRes.json();
    const user = users.find((u) => u.username === username);
    check("found the just-registered user via the admin API", !!user, username);

    console.log("\n== seed a real completed single_point/grad and single_point/nac job, owned by this user ==");
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
grad_job_id = mgr.submit(
    JobSpec(task="single_point", subtype="grad", method="hf", engine="pyscf", molecule=WATER,
            params={"basis": "sto-3g"}),
    owner_user_id=USER_ID,
)
nac_job_id = mgr.submit(
    JobSpec(task="single_point", subtype="nac", method="casscf", engine="pyscf", molecule=WATER,
            params={"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
                    "n_states": 2, "state_pairs": [[1, 2]]}),
    owner_user_id=USER_ID,
)
thread_registry.set_active_job_ids(thread_id, [grad_job_id, nac_job_id])

deadline = time.time() + 180
statuses = {}
while time.time() < deadline:
    statuses = {
        "grad": (mgr.status(grad_job_id) or {}).get("status"),
        "nac": (mgr.status(nac_job_id) or {}).get("status"),
    }
    if all(s in ("completed", "failed", "cancelled") for s in statuses.values()):
        break
    time.sleep(1.0)

print(json.dumps({"thread_id": thread_id, "grad_job_id": grad_job_id, "nac_job_id": nac_job_id, **statuses}))
`;
    const seedOut = execApi(seedCode);
    const seeded = JSON.parse(seedOut.trim().split("\n").pop());
    console.log(`seeded: ${JSON.stringify(seeded)}`);
    check("the seeded gradient job reached status=completed", seeded.grad === "completed", seeded.grad);
    check("the seeded NAC job reached status=completed", seeded.nac === "completed", seeded.nac);

    console.log("\n== open the thread ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(`text=${seeded.grad_job_id}`, { timeout: 30000 });

    console.log("\n== gradient job: open the drawer, GradientSection renders real data ==");
    await page.click(`text=${seeded.grad_job_id}`);
    await page.waitForSelector("text=Gradient (Eh/Bohr)", { timeout: 15000 });
    check("the drawer shows a 'Gradient (Eh/Bohr)' section", await page.isVisible("text=Gradient (Eh/Bohr)"));
    check("it says ground state (no target_state was requested)", await page.isVisible("text=ground state"));
    const gradBody = await page.textContent("body");
    check("the gradient norm is shown", /‖grad‖ = 0\.\d+/.test(gradBody) || gradBody.includes("grad") && /0\.\d{6}/.test(gradBody));
    // Three atom rows (O, H, H), each showing an x/y/z triple. Scoped to the
    // open dialog specifically -- JobsPanel's own job list is ALSO a
    // <table>, and an unscoped locator picked up its rows instead the first
    // time this was run.
    const gradRows = await page.locator('[role="dialog"] table tr').allTextContents();
    const atomRows = gradRows.filter((r) => /^\d+\s*[OH]/.test(r.trim()));
    check("three per-atom gradient rows render (O, H, H)", atomRows.length >= 3, JSON.stringify(gradRows.slice(0, 8)));

    console.log("\n== NAC job: open the drawer, NacSection renders real data ==");
    // Radix Dialog closes on Escape -- more robust than guessing the close
    // button's selector (it carries no aria-label or data-testid).
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    await page.click(`text=${seeded.nac_job_id}`);
    await page.waitForSelector("text=Non-adiabatic coupling (Eh/Bohr)", { timeout: 15000 });
    check("the drawer shows a 'Non-adiabatic coupling (Eh/Bohr)' section",
      await page.isVisible("text=Non-adiabatic coupling (Eh/Bohr)"));
    const nacBody = await page.textContent("body");
    check("the NAC norm is shown", /‖NAC‖ = 0\.\d+/.test(nacBody) || /0\.\d{6}/.test(nacBody));
    check("the state pair is shown as S0 / S1", nacBody.includes("S0") && nacBody.includes("S1"), nacBody.slice(0, 200));

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
