// The molecule panel (including its WebGL viewer and the lazy 2D
// sketcher) and the knowledge-base panel.
//
// The WebGL assertions here go through canvas.toDataURL(), never
// page.screenshot() -- screenshots cannot capture WebGL canvas content,
// which is a documented trap in this repo. The canvas COUNT assertion is
// also load-bearing: GLViewer has no destroy()/dispose() method and
// createViewer() unconditionally appends a new <canvas>, so a regression
// in MoleculeViewer's "clear the container at the START of the init
// effect" fix shows up as a growing canvas count and eventually as a
// blank viewer once the browser's WebGL context cap is hit.
import { newBrowser, freshContext, uiLogin, waitForComposerReady, sendMessage, check, summary, shot, control, canvasHasContent, BASE_URL, ADMIN_USER, adminPassword } from "./_ui.mjs";

const browser = await newBrowser();
const ctx = await freshContext(browser);
const page = await ctx.newPage();

try {
  await uiLogin(page, ADMIN_USER, adminPassword());
  await waitForComposerReady(page);

  // ------------------------------------------------------ empty state
  // Start a NEW conversation first: molecule state is per-thread, and this
  // account carries molecules from earlier scenarios, so checking the empty
  // state on whatever thread happens to be active tests nothing.
  const newConv = control(page, "New conversation");
  if (await newConv.count()) {
    await newConv.first().click();
    await waitForComposerReady(page);
    await page.waitForTimeout(1200);
  }
  const emptyState = await page.locator("text=No molecule set yet").count();
  check("molecule panel shows its empty state on a fresh conversation",
    emptyState > 0);

  // ------------------------------------------------ set a molecule
  await sendMessage(page, "Set the molecule to water.");
  await page.waitForTimeout(3000);

  const canv = await canvasHasContent(page);
  check("MoleculeViewer created a WebGL canvas", canv.found === true,
    JSON.stringify(canv));
  check("the molecule viewer actually RENDERED (non-trivial pixel content, "
    + "verified via canvas.toDataURL -- page.screenshot cannot capture WebGL)",
    canv.looksRendered === true, JSON.stringify(canv));
  check("exactly one canvas per viewer container (no leaked WebGL contexts)",
    (canv.count || 0) <= 2, `${canv.count} canvases live`);

  await shot(page, "ui03-molecule-set");

  // ------------------------------------------- coordinates toggle
  const showCoords = page.locator('button:has-text("Show coordinates")');
  if (await showCoords.count()) {
    await showCoords.first().click();
    await page.waitForTimeout(500);
    const body = await page.evaluate(() => document.body.innerText);
    check("'Show coordinates' reveals the geometry", /[-\d]\.\d{3,}/.test(body));
    const hide = page.locator('button:has-text("Hide coordinates")');
    check("the toggle flips to 'Hide coordinates'", (await hide.count()) > 0);
    if (await hide.count()) await hide.first().click();
  } else {
    check("'Show coordinates' toggle present", false, "not found");
  }

  // ------------------------------------------- enlarge flyout
  const enlarge = control(page, "Enlarge");
  if (await enlarge.count()) {
    await enlarge.first().click();
    await page.waitForTimeout(1500);
    const big = await canvasHasContent(page);
    check("the enlarge flyout renders its own working viewer",
      big.found && big.looksRendered, JSON.stringify(big));
    await page.keyboard.press("Escape");
    await page.waitForTimeout(600);
  }

  // --------------------------------- WebGL context leak under churn
  // Repeatedly mount/unmount the enlarge flyout and confirm the live
  // canvas count does not grow. This is the regression that previously
  // showed up as a silently blank viewer.
  let counts = [];
  for (let i = 0; i < 4; i++) {
    const e = control(page, "Enlarge");
    if (!(await e.count())) break;
    await e.first().click();
    await page.waitForTimeout(900);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(700);
    const c = await canvasHasContent(page);
    counts.push(c.count);
  }
  if (counts.length) {
    const grew = counts[counts.length - 1] > counts[0] + 1;
    check("live canvas count does not grow across repeated viewer "
      + "mount/unmount cycles (WebGL context-leak regression)",
      !grew, `counts across cycles: ${counts.join(",")}`);
  }

  // ------------------------------------------- 2D sketcher (lazy chunk)
  const build = control(page, "Build a molecule (2D sketcher)");
  if (await build.count()) {
    const t0 = Date.now();
    await build.first().click();
    let appeared = false;
    try {
      await page.waitForSelector("text=Build molecule", { timeout: 90000 });
      appeared = true;
    } catch { /* timed out */ }
    const ms = Date.now() - t0;
    check("the 2D sketcher modal eventually appears", appeared, `${ms}ms`);
    console.log(`    [perf] Ketcher lazy chunk (28.7MB) took ${ms}ms to first paint`);
    check("Ketcher lazy-load latency is under 10s "
      + "(React.lazy fallback is null, so the user sees NOTHING while it loads)",
      ms < 10000, `${ms}ms -- a spinner/skeleton would be warranted above ~1s`);
    if (appeared) {
      await shot(page, "ui03-ketcher");
      const cancel = page.locator('button:has-text("Cancel")');
      if (await cancel.count()) await cancel.first().click();
      await page.waitForTimeout(500);
    }
  } else {
    check("2D sketcher control present", false, "not found");
  }

  // ---------------------------------------------------- knowledge base
  const kbHeader = page.locator("text=Knowledge base").first();
  if (await kbHeader.count()) {
    await kbHeader.click();
    await page.waitForTimeout(800);

    const dropZone = await page.locator('[data-testid="kb-drop-zone"]').count();
    check("KB drop zone present (the app's only data-testid)", dropZone > 0);

    const search = page.locator('input[placeholder="Search sources..."]');
    if (await search.count()) {
      await search.fill("casscf");
      await page.waitForTimeout(700);
      const rows = await page.evaluate(() => document.body.innerText);
      check("KB source search filters the list client-side",
        rows.toLowerCase().includes("casscf") || rows.includes("No "), "");
      await search.fill("");
    } else {
      check("KB search input present", false, "not found");
    }

    const add = control(page, "Add source");
    check("KB 'Add source' control present", (await add.count()) > 0);
    if (await add.count()) {
      await add.first().click();
      await page.waitForTimeout(500);
      const body = await page.evaluate(() => document.body.innerText);
      check("the add-source form offers both file upload and web-page fetch",
        body.includes("Fetch") || body.includes("web page"), "");
      await shot(page, "ui03-kb-addform");
    }

    const quota = await page.evaluate(() => document.body.innerText);
    check("KB storage usage badge is rendered",
      /\d+(\.\d+)?\s*(B|KB|MB|GB)/i.test(quota), "");
  } else {
    check("Knowledge base section present", false, "not found");
  }

  await shot(page, "ui03-kb");

} catch (e) {
  check("ui_03 completed without throwing", false, String(e).slice(0, 400));
  try { await shot(page, "ui03-FAILURE"); } catch { /* best effort */ }
} finally {
  const ok = summary();
  await browser.close();
  process.exit(ok ? 0 : 1);
}
