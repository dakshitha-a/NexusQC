// P8.3: the live broadening slider on a wigner_spectra master's drawer.
// Real end to end: a real PySCF HF/STO-3G water frequency job, real
// Wigner-sampled geometries drawn from its own normal modes
// (app.chemistry.jobs.wigner.sample_from_source_job -- the same function
// EnsembleOrchestrator itself uses, not a hand-built fixture), and a real
// small (N=6) ensemble of TD-HF single-point sub-jobs the live server's
// own EnsembleOrchestrator dispatches and completes.
//
// The master's own spec/status/result is written by hand rather than via
// JobManager.submit_ensemble() -- same reasoning, and the same known race,
// as tests/frontend/p7_05_drawer_latency.spec.mjs's own pes_1d seed:
// submit_ensemble dispatches its initial wave through a throwaway
// EnsembleOrchestrator instance local to THIS one-off `docker compose exec`
// process, which races the live server's own long-running orchestrator
// thread for the same master. Writing the master's state by hand and never
// calling _dispatch_more here lets the live server's own orchestrator do
// 100% of the dispatching.
//
// Four things under test:
// 1. The panel renders a real broadened spectrum from the real pooled
//    transitions GET /api/jobs/{id}/wigner_transitions returns.
// 2. Moving the slider does NOT fire a new network request -- intercepted
//    via page.route on the wigner_transitions endpoint, counting calls
//    before and after several slider moves.
// 3. The axis is energy in eV, matching the server-rendered final plot
//    (render_wigner_ensemble_spectrum) rather than the nm axis a
//    single-job UV/Vis spectrum uses.
// 4. The double-ended energy-window slider actually narrows the plotted
//    range -- checked against the rendered axis tick labels, not just the
//    numeric readout, since the readout could move while the chart stayed
//    put.
//
// Run against the real docker-compose dev stack (needs a rebuilt
// frontend/dist -- nginx serves it from a host bind mount):
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/p8_03_wigner_broadening.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_p803_" + Math.random().toString(36).slice(2, 8);
const N_SAMPLES = 6;

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 240000,
  }).trim();
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_p803_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  let seededMasterId = null;

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

    console.log(`\n== seed a real frequency job + a real ${N_SAMPLES}-sample Wigner ensemble ==`);
    const seedCode = `
import json, random, time
from app.agent import threads as thread_registry
from app.auth.models import record_ownership
from app.chemistry.jobs import pyscf_runner
from app.chemistry.jobs.base import (
    JobResult, JobSpec, get_job_manager, read_status, sub_job_ids_of, write_result, write_status, _write_path_xyz,
)
from app.chemistry.jobs.dispatch import resolve_runner
from app.chemistry.jobs.wigner import sample_from_source_job

USER_ID = "${user.id}"
N_SAMPLES = ${N_SAMPLES}
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}

freq_spec = JobSpec(task="freq", subtype="", method="hf", engine="pyscf", molecule=WATER,
                     job_id="p803freq" + str(random.randint(0, 999999)))
freq_job_dir = freq_spec.job_dir()
(freq_job_dir / "spec.json").write_text(json.dumps(freq_spec.to_dict(), indent=2))
freq_result = pyscf_runner.run_frequency(WATER, {"method": "hf", "basis": "sto-3g", "_job_dir": str(freq_job_dir)})
write_status(freq_spec.job_id, "completed", "seeded")
write_result(JobResult(freq_spec.job_id, "completed", summary=freq_result["summary"],
                        artifacts=freq_result.get("artifacts", {})))

random_seed = random.randint(0, 2**31 - 1)
samples, diagnostics = sample_from_source_job(
    WATER, freq_result["summary"], n_samples=N_SAMPLES, random_seed=random_seed)

thread = thread_registry.create_thread(label="${THREAD_LABEL}")
thread_id = thread["thread_id"]
record_ownership("thread", thread_id, USER_ID)

master = JobSpec(task="wigner_spectra", subtype="", method="hf", engine="pyscf", molecule=WATER,
                  params={"basis": "sto-3g", "n_states": 2, "n_samples": N_SAMPLES,
                          "random_seed": random_seed, "temperature_K": 0.0,
                          "source_frequency_job_id": freq_spec.job_id})
job_dir = master.job_dir()
(job_dir / "spec.json").write_text(json.dumps(master.to_dict(), indent=2))
write_status(master.job_id, "running", f"submitting an initial wave of samples (0 of {N_SAMPLES})")
record_ownership("job", master.job_id, USER_ID)
ensemble_xyz = _write_path_xyz(job_dir, samples, filename="ensemble.xyz")
scan_job_type, _ = resolve_runner("single_point", "ee", master.method)
summary = {
    "scan_job_type": scan_job_type, "source_frequency_job_id": freq_spec.job_id,
    "engine": master.engine, "n_samples": N_SAMPLES, "n_dispatched": 0, "n_complete": 0,
    "random_seed": random_seed, "temperature_K": 0.0, **diagnostics,
}
write_result(JobResult(master.job_id, "running", summary=summary, artifacts={"ensemble_xyz": ensemble_xyz}))
master_id = master.job_id
thread_registry.set_active_job_ids(thread_id, [master_id])

deadline = time.time() + 280
sub_ids = []
while time.time() < deadline:
    sub_ids = sub_job_ids_of(master_id)
    statuses = [(read_status(sid) or {}).get("status") for sid in sub_ids]
    if len(sub_ids) == N_SAMPLES and all(s in ("completed", "failed") for s in statuses):
        break
    time.sleep(1)

print(json.dumps({
    "thread_id": thread_id, "master_id": master_id, "freq_job_id": freq_spec.job_id,
    "n_dispatched": len(sub_ids),
    "n_complete": sum(1 for sid in sub_ids if (read_status(sid) or {}).get("status") == "completed"),
}))
`;
    const seedOut = execApi(seedCode);
    const seeded = JSON.parse(seedOut.trim().split("\n").pop());
    seededMasterId = seeded.master_id;
    console.log(`seeded: ${JSON.stringify(seeded)}`);
    check(`all ${N_SAMPLES} samples dispatched`, seeded.n_dispatched === N_SAMPLES, seeded.n_dispatched);
    check(`all ${N_SAMPLES} samples completed`, seeded.n_complete === N_SAMPLES, seeded.n_complete);

    console.log("\n== open the thread and the master's drawer ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(`text=${seeded.master_id}`, { timeout: 30000 });
    await page.click(`text=${seeded.master_id}`);
    await page.waitForSelector('[data-testid="wigner-broadening-panel"]', { timeout: 30000 });
    check("the live broadening panel renders", true);

    console.log("\n== the panel shows a real broadened spectrum from real pooled transitions ==");
    const svgPathsCount = await page.locator('[data-testid="wigner-broadening-panel"] svg path').count();
    check("the chart drew at least one path (a real curve, not an empty chart)", svgPathsCount > 0, svgPathsCount);
    const initialFwhm = await page.textContent('[data-testid="wigner-fwhm-value"]');
    check("the FWHM readout starts at the ensemble default (0.20)", initialFwhm.trim() === "0.20", initialFwhm);

    console.log("\n== moving the slider re-broadens WITHOUT a new network request ==");
    let transitionsRequestCount = 0;
    await page.route("**/api/jobs/*/wigner_transitions", (route) => {
      transitionsRequestCount += 1;
      route.continue();
    });
    // Let one settle (e.g. a resource still in flight from drawer-open)
    // before the baseline is taken, matching the "count around the move,
    // not around the initial load" shape a request-interception assertion
    // needs.
    await page.waitForTimeout(500);
    const before = transitionsRequestCount;
    const slider = page.locator('[data-testid="wigner-fwhm-slider"]');
    await slider.focus();
    for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(300);
    const afterMove = transitionsRequestCount;
    check("no new GET .../wigner_transitions request fired from 5 slider moves",
      afterMove === before, `before=${before} after=${afterMove}`);

    const movedFwhm = await page.textContent('[data-testid="wigner-fwhm-value"]');
    check("the FWHM readout actually changed after the moves", movedFwhm.trim() !== initialFwhm.trim(), movedFwhm);
    const svgPathsAfter = await page.locator('[data-testid="wigner-broadening-panel"] svg path').count();
    check("the chart still renders a real curve after re-broadening", svgPathsAfter > 0, svgPathsAfter);

    console.log("\n== the axis is eV, not nm ==");
    const panelText = await page.innerText('[data-testid="wigner-broadening-panel"]');
    check("the chart's x-axis is labelled in eV", /Energy \(eV\)/.test(panelText), panelText.slice(0, 200));
    check("the chart is NOT labelled in nm", !/Wavelength \(nm\)/.test(panelText), panelText.slice(0, 200));

    console.log("\n== the double-ended energy window narrows the plotted range ==");
    // The discriminating read is the x-axis tick text, not the window
    // readout: the readout is the slider's own state, so it would change
    // even if the chart ignored it entirely. Tick labels come from the
    // data actually handed to MiniLineChart.
    const axisTicks = async () => {
      const texts = await page.locator('[data-testid="wigner-broadening-panel"] svg text').allTextContents();
      return texts.map((t) => Number(t)).filter((n) => Number.isFinite(n));
    };
    const ticksBefore = await axisTicks();
    const windowBefore = (await page.textContent('[data-testid="wigner-window-value"]')).trim();
    check("the energy window starts at the full pooled extent", /^\d+\.\d\d-\d+\.\d\d$/.test(windowBefore), windowBefore);

    const requestsBeforeWindow = transitionsRequestCount;
    const minThumb = page.locator('[data-testid="wigner-window-min"]');
    await minThumb.focus();
    for (let i = 0; i < 12; i++) await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(300);
    const windowAfter = (await page.textContent('[data-testid="wigner-window-value"]')).trim();
    check("dragging the lower thumb moved the window's lower bound",
      windowAfter !== windowBefore, `before=${windowBefore} after=${windowAfter}`);
    check("narrowing the window fired no new network request either",
      transitionsRequestCount === requestsBeforeWindow,
      `before=${requestsBeforeWindow} after=${transitionsRequestCount}`);

    const ticksAfter = await axisTicks();
    const spanOf = (ts) => (ts.length ? Math.max(...ts) - Math.min(...ts) : NaN);
    check("the chart's own x-axis range actually shrank",
      spanOf(ticksAfter) < spanOf(ticksBefore),
      `before span=${spanOf(ticksBefore)} after span=${spanOf(ticksAfter)}`);

    const resetVisible = await page.locator('[data-testid="wigner-window-reset"]').isVisible();
    check("a reset control appears once the window has been narrowed", resetVisible, resetVisible);
    await page.click('[data-testid="wigner-window-reset"]');
    await page.waitForTimeout(200);
    const windowReset = (await page.textContent('[data-testid="wigner-window-value"]')).trim();
    check("reset restores the full pooled extent", windowReset === windowBefore,
      `original=${windowBefore} afterReset=${windowReset}`);

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
    if (seededMasterId) {
      try {
        execApi(`from app.chemistry.jobs.base import get_job_manager\n`
          + `get_job_manager().cancel("${seededMasterId}")`);
      } catch (e) {
        console.log(`  (cleanup) failed to cancel seeded master ${seededMasterId}: ${String(e).slice(0, 200)}`);
      }
    }
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
