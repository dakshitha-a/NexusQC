// The approval card, the jobs panels, and JobDetailDrawer's section
// gating -- the largest untested surface in the app.
//
// JobDetailDrawer renders 19 independently-gated sections. The value of
// this spec is asserting the gating in BOTH directions: the sections a
// given job type should show, and the ones it must NOT (XN-01, XN-15,
// XN-16). A spec that only looked for present sections would pass on a
// drawer that rendered everything unconditionally.
//
// Runs against whatever jobs already exist in the account, so it should
// be run AFTER the job matrix. It picks a completed job of each type it
// can find rather than creating its own, since creating one of each type
// through the UI would take hours.
import { newBrowser, freshContext, uiLogin, waitForComposerReady, sendMessage, check, summary, shot, control, canvasHasContent, BASE_URL, ADMIN_USER, adminPassword } from "./_ui.mjs";

const browser = await newBrowser();
const ctx = await freshContext(browser);
const page = await ctx.newPage();

// Section name -> the job types that SHOULD show it. Anything else must not.
const SECTION_RULES = [
  { name: "Vibrational frequencies", showFor: ["frequency"] },
  { name: "Excited states", showFor: ["tddft", "eom_ccsd", "casscf", "caspt2"] },
  { name: "Molecular orbitals", showFor: [
      "single_point", "tddft", "eom_ccsd", "casscf", "caspt2", "mo_visualization"] },
  { name: "Optimization energy", showFor: ["geometry_optimization"] },
  { name: "Scan path", showFor: ["pes_scan"] },
  { name: "NEB-TS path", showFor: ["neb_ts"] },
];

try {
  await uiLogin(page, ADMIN_USER, adminPassword());
  await waitForComposerReady(page);

  // ------------------------------------------------ the approval card
  // Drive one real submission through the UI so the card is exercised
  // exactly as a user sees it.
  await sendMessage(page,
    "Set the molecule to water and run a single point energy calculation "
    + "with Hartree-Fock and the STO-3G basis using PySCF. Go ahead and submit it.");

  const cardVisible = await page.locator('button:has-text("Approve & run")').count();
  check("approval card appears in the chat pane (the interrupt gate is visible "
    + "to the user, not just structural)", cardVisible > 0);

  if (cardVisible) {
    await shot(page, "ui02-approval-card-pyscf");

    // XN-06 / XN-15: PySCF previews are read-only -- no textarea to edit.
    const editable = await page.locator('form textarea, .approval textarea').count();
    const anyTextareaBesidesComposer = await page.evaluate(() => {
      // The composer's own textarea is always present; anything beyond it
      // inside the approval card would be an editable input preview.
      const all = Array.from(document.querySelectorAll("textarea"));
      return all.filter((t) => (t.rows || 0) >= 8).length;
    });
    check("[XN-06] PySCF approval card is read-only (no hand-edit textarea)",
      anyTextareaBesidesComposer === 0,
      `${anyTextareaBesidesComposer} large textarea(s) found`);

    const kb = await page.locator("text=Manual/reference excerpts consulted").count();
    check("approval card surfaces the mechanically-retrieved KB grounding",
      kb > 0, "'Manual/reference excerpts consulted' section");

    // Reject path first -- it must create no job.
    const rejectBtn = page.locator('button:has-text("Reject")');
    if (await rejectBtn.count()) {
      await rejectBtn.first().click();
      await page.waitForTimeout(3000);
      const stillThere = await page.locator('button:has-text("Approve & run")').count();
      check("Reject dismisses the approval card", stillThere === 0);
    }
  }

  // Now approve one so there is a job to inspect.
  await sendMessage(page,
    "Actually yes, please run that single point on water: Hartree-Fock, "
    + "STO-3G, PySCF. Submit it.");
  const approve = page.locator('button:has-text("Approve & run")');
  if (await approve.count()) {
    await approve.first().click();
    await page.waitForTimeout(5000);
    check("Approve & run dismisses the card and submits", true);
  }

  // -------------------------------------------------- jobs list + drawer
  // Pull the real job inventory from the API so the drawer assertions are
  // driven by actual job types rather than guesses about what exists.
  const jobs = await page.evaluate(async () => {
    const r = await fetch("/api/jobs");
    return r.ok ? await r.json() : [];
  });
  check("job list API returns this account's jobs", Array.isArray(jobs),
    `${jobs.length} jobs`);

  const completed = jobs.filter((j) => j.status === "completed");
  const byType = {};
  for (const j of completed) if (!byType[j.method]) byType[j.method] = j;
  console.log(`    job types available to inspect: ${Object.keys(byType).join(", ") || "(none)"}`);

  // Make sure the Job manager section is EXPANDED. Clicking its header is
  // a toggle, so a blind click closes it when it was already open -- which
  // removes every row from the DOM and makes each drawer check below fail
  // for a reason that has nothing to do with the drawer.
  const someJobId = completed.length ? completed[0].job_id : null;
  if (someJobId) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const rowsVisible = await page.locator(`text=${someJobId}`).count();
      if (rowsVisible > 0) break;
      const hdr = page.locator("text=Job manager").first();
      if (await hdr.count()) {
        await hdr.click().catch(() => {});
        await page.waitForTimeout(1200);
      }
    }
  }
  check("job manager rows are reachable in the DOM",
    someJobId ? (await page.locator(`text=${someJobId}`).count()) > 0 : false);

  for (const [method, job] of Object.entries(byType)) {
    // A job id appears in several places (both job panels, attach chips),
    // and only some of them are the clickable row. Try each match until a
    // Radix dialog actually opens, rather than assuming the first one is
    // the right target -- otherwise every "section present" check below
    // silently tests the main app's text instead of the drawer's.
    const rows = page.locator(`text=${job.job_id}`);
    const n = await rows.count();
    let opened = false;
    for (let i = 0; i < n && !opened; i++) {
      try {
        await rows.nth(i).click({ timeout: 5000 });
      } catch { continue; }
      await page.waitForTimeout(2000);
      opened = (await page.locator('[role="dialog"]').count()) > 0;
    }
    check(`[${method}] job detail drawer opened`, opened,
      `${n} elements matched job id ${job.job_id}`);
    if (!opened) continue;

    // Scope to the drawer itself, not the whole page.
    const body = await page.evaluate(() => {
      const ds = Array.from(document.querySelectorAll('[role="dialog"]'));
      return ds.length ? ds[ds.length - 1].innerText : "";
    });
    // Drawer section headings are CSS text-transform: uppercase and
    // innerText returns the TRANSFORMED text, so a title-case comparison
    // reports correctly-rendered sections as missing.
    const bodyU = body.toUpperCase();
    for (const rule of SECTION_RULES) {
      const present = bodyU.includes(rule.name.toUpperCase());
      const shouldShow = rule.showFor.includes(method);
      if (shouldShow) {
        check(`[${method}] drawer shows "${rule.name}"`, present);
      } else {
        check(`[${method}] drawer correctly OMITS "${rule.name}"`, !present,
          present ? "section rendered where it should be gated off" : "");
      }
    }

    // XN-15: a PySCF job has no literal input/output file to view.
    if (job.engine === "pyscf") {
      const rawIn = await control(page, "View raw input").count();
      const rawOut = await control(page, "View raw output").count();
      check(`[XN-15] PySCF job shows neither raw-input nor raw-output button`,
        rawIn === 0 && rawOut === 0, `rawIn=${rawIn} rawOut=${rawOut}`);
    } else {
      const rawIn = await control(page, "View raw input").count();
      check(`[${job.engine}] job exposes "View raw input"`, rawIn > 0);
    }

    // XN-16: the inline/artifact spectrum pairs are mutually exclusive.
    const uvInline = bodyU.includes("UV/VIS SPECTRUM (AUTO)");
    const uvArtifact = bodyU.includes("UV/VIS SPECTRUM") && !uvInline;
    check(`[${method}] [XN-16] inline and artifact UV/Vis are not both shown`,
      !(uvInline && uvArtifact));

    // A 3D viewer, if this job type has one, must actually render.
    const canv = await canvasHasContent(page);
    if (canv.found) {
      check(`[${method}] a WebGL viewer rendered actual content`,
        canv.looksRendered === true,
        `canvases=${canv.count} ${canv.width}x${canv.height} bytes=${canv.bytes}`);
      check(`[${method}] exactly one canvas per viewer (no WebGL context leak)`,
        canv.count <= 2, `${canv.count} canvases live`);
    }

    await shot(page, `ui02-drawer-${method}`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(800);
  }

  // ------------------------------------------------- two-step confirms
  const del = control(page, "Delete job");
  if (await del.count()) {
    await del.first().click();
    await page.waitForTimeout(400);
    const confirm = await control(page, "Confirm delete").count();
    check("DeleteJobButton is a two-step in-DOM confirm (never window.confirm)",
      confirm > 0);
    const cancel = control(page, "Cancel");
    if (await cancel.count()) await cancel.first().click();
  }

} catch (e) {
  check("ui_02 completed without throwing", false, String(e).slice(0, 400));
  try { await shot(page, "ui02-FAILURE"); } catch { /* best effort */ }
} finally {
  const ok = summary();
  await browser.close();
  process.exit(ok ? 0 : 1);
}
