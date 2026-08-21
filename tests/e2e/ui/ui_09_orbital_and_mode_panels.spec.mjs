// The orbital and vibrational-mode panels, expanded.
//
// Two things are under test, and the first one is why this file exists.
//
// **The viewer used to be left loading after a scrubber drag.** Reported
// against the expanded orbital panel, reproduced here, and the mechanism was
// reference identity: FrameScrubber fires onChange on every pointermove -- many
// of which land inside the SAME orbital's slice of track -- JobDetailDrawer
// answered each with a fresh `{index, spin}` object, and MoCubeViewer's fetch
// effect had that object in its dependency array. React compares by reference,
// so every pointermove re-fired the effect, and every re-fire is a real
// orca_plot or molden->cube run on the server. A measured drag across a
// 36-orbital table issued **42 POSTs**, of which several were duplicates of the
// same index; the browser's six-connections-per-origin limit queued them, the
// one the user was waiting for went last, and the spinner was still turning ten
// seconds after the drag ended. So the assertion that matters here is a
// **request count**, not an appearance: a screenshot of a spinner proves
// nothing about why it is spinning.
//
// **The tables now live inside the panels.** Expanded, a panel is `fixed
// inset-6` and covers everything behind it -- which is where the orbital and
// frequency tables used to be, so the only way to reach a different orbital or
// mode was to collapse first. Both tables are now a column beside the viewer,
// clickable in place, with the scrubber kept as a second way to move.
//
// Notes on how this is driven:
//   * page.screenshot() cannot capture WebGL. Every "did it render" check goes
//     through canvas.toDataURL() -- see canvasHasContent in _ui.mjs.
//   * Every panel's expand toggle carries the same data-testid, so the panel is
//     selected by the `data-panel` name ExpandablePanel puts on its wrapper
//     rather than by position in the drawer.
//   * The subject jobs are found by scanning the real job inventory for one
//     that has an orbital table with a renderable wavefunction behind it, and
//     one with normal modes. Nothing is hardcoded, and a missing fixture fails
//     loudly rather than passing vacuously.
import {
  BASE_URL, newBrowser, freshContext, uiLogin, check, summary, shot,
  ADMIN_USER, adminPassword,
} from "./_ui.mjs";

const browser = await newBrowser();
const page = await (await freshContext(browser)).newPage();
page.setDefaultTimeout(60000);

// Every lazily-rendered cube request, so a drag can be counted rather than
// eyeballed.
const cubeReqs = [];
page.on("request", (r) => {
  const m = r.url().match(/\/api\/jobs\/[^/]+\/orbitals\/(\d+)\/cube/);
  if (m) cubeReqs.push(m[1]);
});

// The auth layer is inert without QC_AGENT_DATABASE_URL, so a spec pointed at a
// bare `server.main` + Vite pair (QC_AGENT_TEST_BASE_URL) never sees a login
// screen at all. Log in only if there is one to log into.
await page.goto(`${BASE_URL}/`);
await page.waitForTimeout(3000);
if (await page.locator('input[placeholder="Username or email"]').count()) {
  await uiLogin(page, ADMIN_USER, adminPassword());
}
await page.waitForSelector("textarea", { timeout: 60000 });

// ---------------------------------------------------------------- fixtures
// A job qualifies for the orbital half only if its cubes can actually be
// rendered on demand: PySCF and BAGEL need a molden artifact, ORCA needs its
// retained input.gbw (which the API reports as a raw_output sibling, so engine
// is the proxy). neb_ts jobs are excluded because the drawer deliberately
// renders their orbitals through NebFrameViewer instead.
const fixtures = await page.evaluate(async () => {
  const list = await (await fetch("/api/jobs")).json();
  const done = list.filter((j) => j.status === "completed");
  let orbital = null, freq = null;
  for (const j of done.slice(0, 120)) {
    if (orbital && freq) break;
    const d = await (await fetch(`/api/jobs/${j.job_id}`)).json();
    const s = d.summary || {}, a = d.artifacts || {};
    const rows = (s.orbital_table || []).length;
    if (!orbital && rows >= 6 && j.task !== "neb_ts" && (a.molden || j.engine === "orca")) {
      orbital = { id: j.job_id, rows };
    }
    if (!freq && (s.normal_modes || []).length > 1) {
      freq = { id: j.job_id, modes: s.normal_modes.length };
    }
  }
  return { orbital, freq };
});
check("a job with a renderable orbital table exists to test against",
  !!fixtures.orbital, JSON.stringify(fixtures.orbital));
check("a job with normal modes exists to test against",
  !!fixtures.freq, JSON.stringify(fixtures.freq));

/** Open one job's detail drawer. A job id appears in several places (both job
 *  panels, attach chips) and only some of them are the clickable row, so try
 *  each match until a dialog actually opens. */
async function openJob(id) {
  while (await page.locator('[role="dialog"]').count()) {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(600);
  }
  for (let attempt = 0; attempt < 3; attempt++) {
    if ((await page.locator(`text=${id}`).count()) > 0) break;
    const hdr = page.locator("text=Job manager").first();
    if (await hdr.count()) {
      await hdr.click().catch(() => {});
      await page.waitForTimeout(1200);
    }
  }
  const rows = page.locator(`text=${id}`);
  for (let i = 0; i < (await rows.count()); i++) {
    try { await rows.nth(i).click({ timeout: 5000 }); } catch { continue; }
    await page.waitForTimeout(1500);
    if (await page.locator('[role="dialog"]').count()) return true;
  }
  return false;
}

/** Serialized pixels of the last canvas in the open drawer. toDataURL, not a
 *  screenshot: WebGL content does not survive page.screenshot(). */
const canvasPixels = () => page.evaluate(() => {
  const c = Array.from(document.querySelectorAll('[role="dialog"] canvas')).pop();
  if (!c) return "";
  try { return c.toDataURL(); } catch { return ""; }
});

const spinning = async () => (await page.locator('[role="dialog"] svg.animate-spin').count()) > 0;

/** Wait for the viewer to stop loading, then a short tail.
 *
 *  Not a fixed sleep. How long one cube takes varies by two orders of
 *  magnitude -- a benzene/STO-3G molden conversion measured 0.4 s here, an ORCA
 *  `orca_plot` subprocess on a bigger basis is seconds, and either can be a
 *  cache hit on a second run -- so a sleep tuned on a warm PySCF fixture would
 *  be flaky on a cold ORCA one and slow on everything. The tail is what makes
 *  the request counts meaningful: any late or superseded request turns the
 *  spinner back on, so a count taken after "no spinner, and still none a
 *  moment later" is a count of everything that was going to happen. */
async function settle(tailMs = 2000) {
  await page.waitForFunction(
    () => document.querySelectorAll('[role="dialog"] svg.animate-spin').length === 0,
    null, { timeout: 120000 },
  ).catch(() => {});
  await page.waitForTimeout(tailMs);
}

/** The two columns' laid-out geometry: is the table on screen, and is it
 *  beside the viewer rather than behind it? */
const columns = (rowSelector) => page.evaluate((sel) => {
  const t = document.querySelector(sel);
  const c = Array.from(document.querySelectorAll('[role="dialog"] canvas')).pop();
  if (!t || !c) return null;
  const a = t.getBoundingClientRect(), b = c.getBoundingClientRect();
  return {
    tableW: Math.round(a.width), tableH: Math.round(a.height),
    tableRight: Math.round(a.right), canvasLeft: Math.round(b.left),
    canvasH: Math.round(b.height),
  };
}, rowSelector);

// ------------------------------------------------------------ orbitals
if (fixtures.orbital) {
  check("the orbital job's drawer opens", await openJob(fixtures.orbital.id));
  const dlg = page.locator('[role="dialog"]').last();
  await dlg.locator("text=Molecular orbitals").first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);

  const orbRows = dlg.locator('[data-testid^="orbital-row-"]');
  check("the orbital table renders inside the collapsed panel",
    (await orbRows.count()) > 1, `${await orbRows.count()} rows`);

  cubeReqs.length = 0;
  await orbRows.nth(2).click();
  await settle();
  check("a row click asks the server for exactly one cube",
    cubeReqs.length === 1, `[${cubeReqs}]`);
  check("the loading spinner clears once the cube arrives", !(await spinning()));
  const collapsedPixels = await canvasPixels();
  check("the isosurface actually renders", collapsedPixels.length > 20000,
    `${collapsedPixels.length} b`);

  await dlg.locator('[data-panel="orbitals"] [data-testid="panel-expand"]').click();
  await page.waitForTimeout(1500);
  const g = await columns('[data-testid^="orbital-row-"]');
  check("expanded: the orbital table is still on screen", !!g && g.tableW > 0 && g.tableH > 0,
    JSON.stringify(g));
  check("expanded: the table sits beside the viewer, not behind it",
    !!g && g.tableRight <= g.canvasLeft + 5);
  check("expanded: the viewer grew", !!g && g.canvasH > 400, `${g?.canvasH}px`);
  check("expanded: the scrubber is offered as well as the rows",
    (await page.locator('[data-testid="frame-scrubber"]').count()) > 0);
  await shot(page, "ui09-orbitals-expanded");

  cubeReqs.length = 0;
  const beforeClick = await canvasPixels();
  await orbRows.nth(0).click();
  await settle();
  check("expanded: a row click asks for exactly one cube", cubeReqs.length === 1, `[${cubeReqs}]`);
  check("expanded: a row click clears the spinner", !(await spinning()));
  const afterClick = await canvasPixels();
  check("expanded: a row click changes what is rendered",
    afterClick !== beforeClick && afterClick.length > 20000);

  // The drag that used to hang. Sixty per cent of the way across the track, in
  // forty steps, so the pointer passes over many orbitals and stops on one that
  // was not selected before.
  const box = await page.locator('[data-testid="frame-scrubber"]').last().boundingBox();
  cubeReqs.length = 0;
  const beforeDrag = await canvasPixels();
  await page.mouse.move(box.x + 5, box.y + box.height / 2);
  await page.mouse.down();
  for (let s = 0; s <= 40; s++) {
    await page.mouse.move(box.x + 5 + ((box.width - 10) * s * 0.6) / 40, box.y + box.height / 2);
    await page.waitForTimeout(40);
  }
  await page.mouse.up();
  const during = cubeReqs.length;
  await settle(3000);
  check("a whole scrubber drag costs at most one cube render",
    cubeReqs.length <= 1, `${during} during the drag, ${cubeReqs.length} in total [${cubeReqs}]`);
  check("the viewer is not left loading after the drag", !(await spinning()));
  const afterDrag = await canvasPixels();
  check("the viewer ends up showing the orbital the drag landed on",
    afterDrag !== beforeDrag && afterDrag.length > 20000);

  // Note the class test: every row carries `hover:bg-surface-raised`, so a
  // substring match finds all of them. The selected row is the one with the
  // bare class.
  const sel = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('[data-testid^="orbital-row-"]'));
    const hit = rows.find((r) => r.className.split(/\s+/).includes("bg-surface-raised"));
    if (!hit) return null;
    const box = hit.closest(".overflow-y-auto").getBoundingClientRect();
    const r = hit.getBoundingClientRect();
    return { row: hit.dataset.testid, inView: r.top >= box.top - 1 && r.bottom <= box.bottom + 1 };
  });
  check("the table highlights the orbital the scrubber landed on", !!sel, JSON.stringify(sel));
  check("and scrolls that row into view, so the two controls agree", sel?.inView === true);
  await shot(page, "ui09-orbitals-after-drag");
}

// ------------------------------------------------------- vibrational modes
if (fixtures.freq) {
  check("the frequency job's drawer opens", await openJob(fixtures.freq.id));
  const dlg = page.locator('[role="dialog"]').last();
  await dlg.locator("text=Vibrational frequencies").first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);

  const vibRows = dlg.locator('[data-testid^="vibration-row-"]');
  check("the frequency table renders inside the collapsed panel",
    (await vibRows.count()) > 1, `${await vibRows.count()} rows`);
  await vibRows.nth(0).click();
  await page.waitForTimeout(3000);
  check("clicking a row starts the animation", (await dlg.locator("canvas").count()) > 0);

  await dlg.locator('[data-panel="vibrations"] [data-testid="panel-expand"]').click();
  await page.waitForTimeout(1500);
  const g = await columns('[data-testid^="vibration-row-"]');
  check("expanded: the frequency table sits beside the animation",
    !!g && g.tableW > 0 && g.tableRight <= g.canvasLeft + 5, JSON.stringify(g));

  const before = await canvasPixels();
  await vibRows.nth(2).click();
  await page.waitForTimeout(3000);
  const after = await canvasPixels();
  check("expanded: clicking a row switches modes without collapsing first",
    after !== before && after.length > 20000);
  await shot(page, "ui09-modes-expanded");
}

const allPassed = summary();
await browser.close();
process.exit(allPassed ? 0 : 1);
