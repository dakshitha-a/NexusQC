// The two fields a refinement gained, rendered in a real browser.
//
// An excitation energy is a difference against a state-averaged ground state,
// and a state average can converge to more than one solution: two molecules in
// seven do, and butadiene's two are 872 meV apart. A converged flag does not
// say which one was reached, so without the reference energy beside them two
// runs of one job return different numbers with nothing to say they are
// different answers rather than the same answer measured twice. The drawer now
// shows it.
//
// The second field is the list of states the refinement deliberately did not
// look for. It was permanently empty until this campaign, because the runner
// stripped Rydberg states before refine() ever saw them, so every refinement
// could report all predicted states present whether or not the one the user
// cared about had been dropped on the way in.
//
// Formaldehyde asked for two excited states is the case that can exercise
// both: in aug-cc-pVDZ its S1 is n->pi* and its S2 is n->Rydberg, so the
// refinement solves several roots, which gives a reference energy, and refuses
// one state, which gives a not-looked-for list. A type check cannot tell a
// missing field from an unrendered one, which is why this is a browser test.
//
//   cd frontend && npm run build
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
//     node tests/frontend/cas_19_refinement_energy_and_rydberg.spec.mjs
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, check, summary, BASE_URL,
} from "./_helpers.mjs";

const COMPOSE_DIR = process.env.QC_AGENT_COMPOSE_DIR
  || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const THREAD_LABEL = "qatest_cas19_" + Math.random().toString(36).slice(2, 8);

function execApi(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c", code], {
    cwd: COMPOSE_DIR, encoding: "utf8", timeout: 900000,
  }).trim();
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_cas19_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  // A console message for a failed fetch does not carry the URL, and "some
  // request 401'd" is not a finding anyone can act on. The response listener
  // is what turns it into one.
  const unauthorized = [];
  page.on("response", (r) => {
    if (r.status() === 401) unauthorized.push(`${r.request().method()} ${r.url()}`);
  });

  const seeded = { rec: null, refine: null, thread: null, userId: null };

  try {
    // Through the form rather than the API: the register endpoint is CSRF
    // guarded and a bare request without an Origin header comes back 403,
    // which is also what every other spec here does.
    console.log("\n== register and log in ==");
    await page.goto(`${BASE_URL}/?invite=${token}`, { waitUntil: "domcontentloaded" });
    await page.fill('input[placeholder="Email"]', `${username}@example.test`);
    await page.fill('input[placeholder="Username"]', username);
    await page.fill('input[placeholder="First name"]', "QA");
    await page.fill('input[placeholder="Last name"]', "Tester");
    await page.fill('input[placeholder="Password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('[data-testid="user-menu-open"]', { timeout: 20000 });
    check("registered and logged in", true);

    const usersRes = await adminCtx.request.get(`${BASE_URL}/api/admin/users`);
    const user = (await usersRes.json()).find((u) => u.username === username);
    check("found the just-registered user", !!user, username);
    seeded.userId = user.id;

    console.log("\n== seed a two-state recommendation and its refinement ==");
    const seedCode = `
import json, time
from app.agent import threads as thread_registry
from app.auth.models import record_ownership
from app.chemistry.jobs.base import JobSpec, get_job_manager

USER_ID = "${user.id}"
CH2O = {"name": "formaldehyde", "symbols": ["C", "O", "H", "H"],
        "coords": [[0.0, 0.0, -0.5296], [0.0, 0.0, 0.6746],
                   [0.0, 0.9337, -1.1078], [0.0, -0.9337, -1.1078]],
        "charge": 0, "multiplicity": 1}

thread = thread_registry.create_thread(label="${THREAD_LABEL}")
thread_id = thread["thread_id"]
record_ownership("thread", thread_id, USER_ID)
mgr = get_job_manager()

def wait(job_id, limit=780):
    deadline = time.time() + limit
    while time.time() < deadline:
        s = (mgr.status(job_id) or {}).get("status")
        if s in ("completed", "failed", "cancelled"):
            return s
        time.sleep(1.0)
    return "timeout"

# n_states counts the ground state too, so 3 asks for two excited states.
rec_id = mgr.submit(
    JobSpec(task="cas_reco", subtype="", method="casscf", engine="pyscf",
            molecule=CH2O, params={"n_states": 3}),
    owner_user_id=USER_ID,
)
rec_status = wait(rec_id)

ref_id = mgr.submit(
    JobSpec(task="cas_reco", subtype="refine", method="casscf", engine="pyscf",
            molecule=CH2O,
            params={"n_states": 3, "active_space_source_job_id": rec_id}),
    owner_user_id=USER_ID,
)
ref_status = wait(ref_id)

thread_registry.set_active_job_ids(thread_id, [rec_id, ref_id])
print(json.dumps({"thread_id": thread_id, "rec_id": rec_id, "ref_id": ref_id,
                  "rec": rec_status, "ref": ref_status}))
`;
    const out = execApi(seedCode);
    const s = JSON.parse(out.trim().split("\n").pop());
    console.log(`seeded: ${s.rec_id} (${s.rec}) / ${s.ref_id} (${s.ref})`);
    seeded.rec = s.rec_id;
    seeded.refine = s.ref_id;
    seeded.thread = s.thread_id;
    check("the recommendation job completed", s.rec === "completed", s.rec);
    check("the refinement job completed", s.ref === "completed", s.ref);

    console.log("\n== open the refinement job's drawer ==");
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(`text=${THREAD_LABEL}`, { timeout: 30000 });
    await page.click(`text=${THREAD_LABEL}`);
    await page.waitForSelector(`text=${seeded.refine}`, { timeout: 30000 });
    const jobRow = page.locator(`text=${seeded.refine}`).last();
    await jobRow.scrollIntoViewIfNeeded();
    await jobRow.click();
    await page.waitForSelector('[role="dialog"]', { timeout: 30000 });

    const dialogText = await page.locator('[role="dialog"]').innerText();

    console.log("\n== the reference energy the excitation energies came from ==");
    check("the excited roots are listed at all",
      dialogText.includes("Excited roots found"),
      dialogText.slice(0, 240));
    // Asserted on the element rather than on the dialog's text. The refinement
    // also writes a NOTE containing the same phrase, so a text search passes
    // whether or not this element renders -- which is exactly what happened the
    // first time this spec ran, and it hid a real bug: the field existed on
    // RefineResult and never reached the job summary at all.
    const refEnergy = page.locator('[data-testid="cas-refine-reference-energy"]');
    check("the state-averaged ground-state energy renders beside them",
      (await refEnergy.count()) === 1, `count=${await refEnergy.count()}`);
    const refText = (await refEnergy.count()) ? await refEnergy.innerText() : "";
    check("and it is an actual energy in Hartree, not an empty label",
      /-?\d+\.\d+\s*Ha/.test(refText), refText || "(element absent)");

    console.log("\n== states the refinement deliberately did not look for ==");
    // Drawn only when there is one, so its absence is a legitimate outcome if
    // the analysis basis found no Rydberg state among the two requested.
    // Whether it fired is printed either way; only its correctness is asserted.
    const notLooked = page.locator('[data-testid="cas-refine-not-looked-for"]');
    const hasNotLookedFor = (await notLooked.count()) === 1;
    console.log(`  not-looked-for section present: ${hasNotLookedFor}`);
    if (hasNotLookedFor) {
      check("it names the state rather than only counting it",
        /Deliberately not looked for:\s*\S+->\S+/.test(dialogText),
        (dialogText.match(/Deliberately not looked for:[^\n]*/) || [""])[0]);
      check("and says why a valence space cannot hold one",
        dialogText.includes("diffuse orbitals a valence"),
        (dialogText.match(/Deliberately not looked for:[\s\S]{0,240}/) || [""])[0]);
    } else {
      console.log("  (no Rydberg state among the requested two; nothing to draw)");
    }

    console.log("\n== nothing is drawn twice, and nothing errored ==");
    check("the raw ground_state_energy_ha key is not also a Summary row",
      !dialogText.includes("ground_state_energy_ha"),
      dialogText.slice(0, 240));
    check("no console errors while rendering the drawer",
      consoleErrors.length === 0,
      `${consoleErrors.slice(0, 3).join(" | ")}  ||  401s: ${unauthorized.slice(0, 4).join(", ") || "none"}`);
  } finally {
    console.log("\n== clean up everything this spec created ==");
    if (seeded.rec || seeded.thread) {
      try {
        execApi(`
from app.agent import threads as thread_registry
from app.chemistry.jobs.base import get_job_manager
mgr = get_job_manager()
for jid in ${JSON.stringify([seeded.rec, seeded.refine].filter(Boolean))}:
    try:
        mgr.delete(jid)
    except Exception as exc:
        print("job delete failed:", jid, exc)
try:
    thread_registry.delete_thread("${seeded.thread}")
except Exception as exc:
    print("thread delete failed:", exc)
print("removed the seeded jobs and thread")
`);
      } catch (e) {
        console.log(`cleanup of jobs/thread failed: ${e}`);
      }
    }
    if (seeded.userId) {
      try {
        await adminCtx.request.delete(`${BASE_URL}/api/admin/users/${seeded.userId}`);
        console.log("removed the test user");
      } catch (e) {
        console.log(`cleanup of user failed: ${e}`);
      }
    }
    await browser.close();
  }
  process.exit(summary());
}

main().catch((e) => { console.error(e); process.exit(1); });
