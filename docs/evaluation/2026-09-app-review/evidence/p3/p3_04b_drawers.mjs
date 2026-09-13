// P3.4b: open the drawer of each already-completed, qa_review-owned job by id
// and record which sections render and whether each viewer canvas drew. This
// settles the ui_02 (drawer section gating) and ui_09 (viewer rendering)
// candidates without re-submitting jobs, and gathers the per-job-type viewer
// evidence the job-matrix driver failed to capture (its job tracking broke).
//
// Job ids are passed in QC_P3_JOBS as "label:id,label:id,...".
//
//   QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
//   QC_P3_JOBS="sp_hf:ad0149396ecb,opt:3107af06b050,freq:2850336d406e,ee:6f6f329a6f77" \
//   node docs/evaluation/2026-09-app-review/evidence/p3/p3_04b_drawers.mjs
import fs from "node:fs";
import path from "node:path";
import { start, loginAs, Log, allCanvases, BASE_URL } from "./_p3.mjs";

const L = new Log("p3_04b_drawers");
const jobs = (process.env.QC_P3_JOBS || "").split(",").filter(Boolean).map((s) => {
  const [label, id] = s.split(":"); return { label, id };
});
if (!jobs.length) { console.error("set QC_P3_JOBS=label:id,..."); process.exit(2); }

const browser = await start();
const { ctx, page } = await loginAs(browser, "qa_review");
await page.waitForTimeout(1500);

for (const { label, id } of jobs) {
  await L.observe(page, `drawer-${label}-${id.slice(0,8)}`, async () => {
    // Open the job manager row for this id. It lives in the right dock; scroll
    // it into view and click. If the row is not present (archived/filtered),
    // record that.
    const row = page.locator(`[data-testid="jobmanager-row-${id}"]`);
    const present = await row.count();
    if (!present) return { row_present: false, note: "row not in job manager (filtered/archived?)" };
    await row.scrollIntoViewIfNeeded().catch(() => {});
    await row.click();
    await page.waitForTimeout(2500);
    // Which section headings does the drawer render?
    const sections = await page.evaluate(() => {
      const heads = Array.from(document.querySelectorAll("h1,h2,h3,h4,[data-testid*='section'],[class*='section']"))
        .map((e) => (e.textContent || "").trim()).filter((s) => s && s.length < 60);
      // Named sections the review cares about (gating):
      const has = (s) => document.body.innerText.includes(s);
      return {
        headings: [...new Set(heads)].slice(0, 25),
        molecular_orbitals: has("Molecular orbitals") || has("Orbitals"),
        optimization_energy: has("Optimization energy") || has("Optimization"),
        vibrations: has("Vibration") || has("frequenc") || has("Frequenc"),
        excited_states: has("Excited") || has("excitation"),
        uvvis: has("UV") || has("absorption") || has("Absorption"),
        raw_input: has("View raw input") || has("raw input"),
      };
    });
    // Give any lazy viewer a moment, then read every canvas.
    await page.waitForTimeout(1500);
    const canvases = await allCanvases(page);
    // Download controls and their names (the safename rule).
    const downloads = await page.evaluate(() =>
      Array.from(document.querySelectorAll('a[download], [data-testid^="drawer-download"]'))
        .map((el) => ({ testid: el.getAttribute("data-testid"), download: el.getAttribute("download") })));
    // Close the drawer for the next one.
    await page.locator('[data-testid="panel-close"], [aria-label="Close"]').first().click().catch(() => {});
    await page.waitForTimeout(600);
    return { row_present: true, sections, canvases, downloads, console: page.__console.splice(0) };
  });
}

fs.writeFileSync(path.join(L.shotDir, "requests.json"), JSON.stringify(page.__requests, null, 1));
await ctx.close(); await browser.close();
console.log(`\nevidence: ${L.file}\nscreenshots: ${L.shotDir}/`);
