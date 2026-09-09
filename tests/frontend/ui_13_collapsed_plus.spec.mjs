#!/usr/bin/env node
// A drawer's + button while the drawer is shut.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/ui_13_collapsed_plus.spec.mjs
//
// The bug: Knowledge base, Files and Projects each had a + in their header
// doing `setAdding((a) => !a)`, and the form it reveals lives inside the
// section body, which CollapsibleSection unmounts while collapsed. All three
// default to collapsed, so on a fresh browser the first click flipped the icon
// from + to X and showed nothing at all, and the second flipped it back. Each
// of those buttons also carried an e.stopPropagation() that did nothing, since
// the button is a sibling of the section toggle rather than a child of it.
//
// Two checks per section, and the second is the one that matters: the section
// has to be open AND the form actually visible. Asserting only that the
// section expanded would pass on a version that expands and shows nothing,
// which is a different bug in the same place.
import {
  BASE_URL,
  ADMIN_USER,
  adminPassword,
  newBrowser,
  newContext,
  LOGGED_IN,
  check,
  summary,
} from "./_helpers.mjs";

// section slug, the + button, the form it must reveal
const CASES = [
  ["knowledge-base", "kb-add-toggle", "kb-add-form"],
  ["files", "files-add-toggle", "files-add-form"],
  ["projects", "project-add-toggle", "project-new-name"],
];

const browser = await newBrowser();
const ctx = await newContext(browser);
// Start from the state a fresh browser is in: all three collapsed. That is
// also the default, but layoutStore persists, so a run after somebody expanded
// one by hand would otherwise not be testing the reported case at all.
await ctx.addInitScript(() => {
  window.localStorage.setItem(
    "qc-agent-layout",
    JSON.stringify({
      state: {
        leftRailCollapsed: false,
        rightDockCollapsed: false,
        moleculeCollapsed: false,
        jobsCollapsed: false,
        jobManagerCollapsed: false,
        plotsCollapsed: false,
        kbCollapsed: true,
        filesCollapsed: true,
        projectsCollapsed: true,
        sharesCollapsed: true,
        leftRailWidth: 288,
        rightDockWidth: 420,
      },
      version: 0,
    }),
  );
});
const page = await ctx.newPage();
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
await page.fill('input[type="password"]', adminPassword());
await page.click('[data-testid="auth-submit"]');
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });

for (const [slug, addToggle, formTestId] of CASES) {
  const toggle = page.locator(`[data-testid="section-${slug}-toggle"]`);
  check(
    `${slug} starts collapsed`,
    (await toggle.getAttribute("aria-expanded")) === "false",
    `aria-expanded=${await toggle.getAttribute("aria-expanded")}`,
  );

  await page.click(`[data-testid="${addToggle}"]`);
  await page.waitForTimeout(200);

  check(
    `${slug}: pressing + opens the section`,
    (await toggle.getAttribute("aria-expanded")) === "true",
    `aria-expanded=${await toggle.getAttribute("aria-expanded")}`,
  );
  check(
    `${slug}: and the add form is actually on screen`,
    await page.locator(`[data-testid="${formTestId}"]`).isVisible(),
  );

  // Pressing it again, now that the section is open, closes the form and
  // leaves the section open. Expanding is a one-way effect of the button.
  await page.click(`[data-testid="${addToggle}"]`);
  await page.waitForTimeout(200);
  check(
    `${slug}: pressing + again closes the form`,
    !(await page.locator(`[data-testid="${formTestId}"]`).isVisible()),
  );
  check(
    `${slug}: and leaves the section open`,
    (await toggle.getAttribute("aria-expanded")) === "true",
  );
}

// The same class of bug on the other side of the screen: the collapsed
// instrument dock rendered four <div>s with tooltips, so it told you which
// panels existed and reached none of them. The sidebar had this and fixed it;
// the dock was left behind.
await page.click('[data-testid="shell-collapse-panel"]');
await page.waitForTimeout(200);
for (const [section, panelSlug] of [
  ["molecule", "molecule"],
  ["jobs", "jobs-this-conversation"],
  ["jobManager", "job-manager-all-jobs"],
  ["plots", "plots"],
]) {
  const icon = page.locator(`[data-testid="dock-collapsed-${section}"]`);
  check(`the collapsed dock offers a ${section} control`, await icon.isVisible());
  await icon.click();
  await page.waitForTimeout(250);
  check(
    `and pressing it opens the dock at ${section}`,
    (await page.locator(`[data-testid="section-${panelSlug}-toggle"]`).getAttribute("aria-expanded")) === "true",
  );
  await page.click('[data-testid="shell-collapse-panel"]');
  await page.waitForTimeout(150);
}

await ctx.close();
await browser.close();
process.exit(summary() ? 0 : 1);
