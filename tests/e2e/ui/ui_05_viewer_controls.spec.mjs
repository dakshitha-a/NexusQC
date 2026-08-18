// Regression spec for the viewer control overlay and the camera fit.
//
// Two bugs, both reported against the running app:
//
//  1. The expand/enlarge toggle became invisible in every molecule, orbital
//     and vibration panel once the download button was added -- both claimed
//     `absolute right-1 top-1 z-10`, so the later sibling (the download
//     button, which has a background) painted over the toggle. The assertion
//     below is geometric, not a class check: both controls must be visible
//     AND their bounding boxes must not intersect. A class assertion would
//     pass against any future re-collision that used different classes.
//
//  2. Molecules loaded "always zoomed out and small". Root cause was 3Dmol's
//     own `zoomTo()`, which floors the fitted radius at
//     `config.minimumZoomToDistance || 5` -- so everything under 10 A across
//     was framed identically. See frontend/src/molecule/fitView.ts. The
//     assertion is on real pixels: what fraction of the canvas does the
//     molecule actually cover? Water measured 0.06 x 0.25 before the fix.
//
// As everywhere in this repo, WebGL content is read through
// canvas.toDataURL() in page.evaluate() -- page.screenshot() cannot capture
// it.
import {
  newBrowser, freshContext, uiLogin, sendMessage, check, summary, shot,
  BASE_URL, ADMIN_USER, adminPassword,
} from "./_ui.mjs";

/** Fraction of the canvas covered by non-background pixels, plus whether the
 *  content runs into the frame edge (i.e. is being clipped). */
async function canvasFill(page, index = 0) {
  return page.evaluate((index) => {
    const c = Array.from(document.querySelectorAll("canvas"))[index];
    if (!c) return { found: false };
    const off = document.createElement("canvas");
    off.width = c.width;
    off.height = c.height;
    off.getContext("2d").drawImage(c, 0, 0);
    const { data } = off.getContext("2d").getImageData(0, 0, off.width, off.height);
    let minX = off.width, maxX = -1, minY = off.height, maxY = -1;
    for (let y = 0; y < off.height; y++) {
      for (let x = 0; x < off.width; x++) {
        const i = (y * off.width + x) * 4;
        // Anything meaningfully off the --bg graphite (#14161a) is content.
        if (Math.abs(data[i] - 0x14) + Math.abs(data[i + 1] - 0x16) + Math.abs(data[i + 2] - 0x1a) > 24) {
          if (x < minX) minX = x; if (x > maxX) maxX = x;
          if (y < minY) minY = y; if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX < 0) return { found: true, empty: true };
    return {
      found: true,
      empty: false,
      widthFrac: +((maxX - minX + 1) / off.width).toFixed(3),
      heightFrac: +((maxY - minY + 1) / off.height).toFixed(3),
      clipped: minX <= 1 || minY <= 1 || maxX >= off.width - 2 || maxY >= off.height - 2,
    };
  }, index);
}

function overlaps(a, b) {
  if (!a || !b) return false;
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

const browser = await newBrowser();
const ctx = await freshContext(browser);
const page = await ctx.newPage();
await uiLogin(page, ADMIN_USER, adminPassword());

// ------------------------------------------------ molecule panel + fit
await sendMessage(page, "Set the molecule to water.");
await page.waitForTimeout(2500); // let the viewer settle after its fit

const fill = await canvasFill(page);
check("molecule viewer rendered something", fill.found === true && fill.empty === false,
  JSON.stringify(fill));
// Before the fix water measured 0.06 x 0.25. The floor made every molecule
// under 10 A across share one camera distance, so this is the discriminating
// number -- a regression restoring the default floor drops it straight back.
check("water fills a reasonable share of the viewer (was 0.06 x 0.25 before the fit fix)",
  (fill.heightFrac ?? 0) > 0.45 && (fill.widthFrac ?? 0) > 0.35,
  `fill ${fill.widthFrac} x ${fill.heightFrac}`);
check("the molecule is not clipped at the frame edge", fill.clipped === false,
  `clipped=${fill.clipped}`);
await shot(page, "ui05-molecule-fit");

// ------------------------------------------------ overlay controls
// The job drawer's Structure panel is an ExpandablePanel wrapping a
// MoleculeViewer -- exactly the combination that collided. Checked BEFORE the
// dock drag below, so a layout change cannot be blamed for a failure here.
const jobs = await (await page.request.get(`${BASE_URL}/api/jobs`)).json();
const rows = Array.isArray(jobs) ? jobs : jobs.jobs ?? [];
// Search for a job that actually offers a geometry, rather than assuming the
// first completed one does. Not every job type has one to show -- a scan
// master deliberately has none (JobDetailDrawer gates the control on
// `geometryMolecule && !isScanMaster`) -- so picking rows[0] made this spec's
// result depend on whatever happened to be at the top of the dev stack's job
// list, and it started failing the moment a scan landed there.
const candidates = rows.filter((j) => j.status === "completed").concat(rows).slice(0, 8);

let job = null;
let opened = false;
for (const candidate of candidates) {
  const cells = page.locator(`text=${candidate.job_id}`);
  let thisOpened = false;
  for (let i = 0; i < (await cells.count()); i++) {
    await cells.nth(i).click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(600);
    if ((await page.locator('[role="dialog"]').count()) > 0) { thisOpened = true; break; }
  }
  if (!thisOpened) continue;
  if ((await page.locator('button[title="View geometry"]').count()) > 0) {
    job = candidate;
    opened = true;
    break;
  }
  // Wrong kind of job -- close and try the next.
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
}

if (!job) {
  check("a job with a viewable geometry exists to open the drawer with", false,
    `tried ${candidates.length} job(s); none offered a geometry view`);
} else {
  check("job detail drawer opened", opened, job.job_id);

  // The ExpandablePanel-wrapped MoleculeViewer lives in the geometry flyout
  // the drawer opens, not in the drawer body itself.
  const geometry = page.locator('button[title="View geometry"]');
  const haveGeometry = (await geometry.count()) > 0;
  check("the drawer offers a geometry view", haveGeometry);
  if (haveGeometry) {
    await geometry.first().click();
    await page.waitForTimeout(1200);
  }

  if (haveGeometry) {
    // Scoped to the geometry flyout, NOT page-wide. The molecule panel in the
    // right dock renders its own MoleculeViewer with the same testid, so a
    // page-wide `.first()` silently measures that button instead -- which sits
    // ~500px away from this expand toggle and therefore "passes" the
    // non-overlap assertion below while testing nothing at all.
    const flyout = page.locator('[role="dialog"]').last();
    const expand = flyout.locator('[data-testid="panel-expand"]').first();
    const download = flyout.locator('[data-testid="viewer-download-png"]').first();
    const haveBoth = (await expand.count()) > 0 && (await download.count()) > 0;
    check("both the expand toggle and the download button are present", haveBoth,
      `expand=${await expand.count()} download=${await download.count()}`);

    if (haveBoth) {
      check("the expand toggle is visible", await expand.isVisible());
      check("the download button is visible", await download.isVisible());
      const eb = await expand.boundingBox();
      const db = await download.boundingBox();
      // The actual bug: same corner, same z-index, download painted on top.
      check("the two controls do not overlap", !overlaps(eb, db),
        `expand=${JSON.stringify(eb)} download=${JSON.stringify(db)}`);
      // They should be in the SAME control row -- adjacent, not merely
      // non-overlapping. Two controls 500px apart would also satisfy the
      // check above while meaning the overlay slot never took effect.
      check("both controls sit in one control row (same top, side by side)",
        eb && db && Math.abs(eb.y - db.y) < 12 && Math.abs(eb.x - db.x) < 60,
        `dy=${eb && db ? Math.abs(eb.y - db.y).toFixed(1) : "?"} dx=${eb && db ? Math.abs(eb.x - db.x).toFixed(1) : "?"}`);

      // And the toggle still works -- being visible is not the same as being
      // reachable, since an invisible sibling could still be eating clicks.
      await expand.click();
      await page.waitForTimeout(600);
      const collapse = page.locator('button[title="Collapse"]');
      check("clicking expand actually expanded the panel", (await collapse.count()) > 0);
      await shot(page, "ui05-panel-expanded");
      if (await collapse.count()) await collapse.first().click();
    }
  }
  // Close the geometry flyout and then the drawer. Escape rather than
  // clicking an X: both are Radix dialogs, so while either is open the drag
  // below hits its overlay instead of the resize handle -- and the canvas the
  // check reads would be the flyout's, not the dock's.
  for (let i = 0; i < 3 && (await page.locator('[role="dialog"]').count()) > 0; i++) {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
  }
  check("all dialogs closed before the resize check",
    (await page.locator('[role="dialog"]').count()) === 0);
}

// ------------------------------------------------ dock resize re-fits
// RightDock is drag-resizable and 3Dmol never observed that, so the canvas
// kept its old pixel width inside a box that had changed size around it. Last,
// because it deliberately changes the layout every check above depends on.
const before = await page.evaluate(() => {
  const c = document.querySelector("canvas");
  return c ? c.width : null;
});
const handle = page.locator('[aria-label*="instrument panel"]');
if (await handle.count()) {
  const box = await handle.first().boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x - 160, box.y + box.height / 2, { steps: 10 });
    await page.mouse.up();
    await page.waitForTimeout(800);
  }
}
const after = await page.evaluate(() => {
  const c = document.querySelector("canvas");
  return c ? c.width : null;
});
check("the viewer canvas resizes when the dock is dragged wider",
  before != null && after != null && after !== before,
  `canvas width ${before} -> ${after}`);

await browser.close();
process.exit(summary() ? 0 : 1);
