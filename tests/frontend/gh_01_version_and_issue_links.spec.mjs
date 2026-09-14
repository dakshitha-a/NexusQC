// GH-01: the app tells you what it is running, and every link into the
// public issue tracker carries that version and opens the right form.
//
// Three surfaces, one number. Help -> About shows "NexusQC <version>
// (<commit>)" read from /api/version (the SERVER's build, not this tab's), the
// bug-report flyout's "Open on GitHub instead" prefills the form with that
// version and the text typed so far, and the admin inbox's "File on GitHub"
// prefills it with the build the report was filed against. None of them
// navigate anywhere here: the hrefs are inspected, not followed, because a
// test must never file an issue on the real public repository.
//
// The last part files a real in-app report and reads it back from the admin
// inbox, which is what proves the server stamps build_commit, build_version
// and user_agent on it. The report is deleted at the end.
import { newBrowser, newContext, adminApiLogin, check, summary, LOGGED_IN, BASE_URL, openUserMenu, randSuffix } from "./_helpers.mjs";

const PUBLIC = "https://github.com/dakshitha-a/NexusQC/issues/new?";

function params(href) {
  return new URL(href).searchParams;
}

async function main() {
  const browser = await newBrowser();
  const ctx = await newContext(browser);
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: BASE_URL });
  // Logged in as the admin so one session can do all three surfaces.
  await adminApiLogin(ctx);
  const page = await ctx.newPage();
  await page.goto(BASE_URL);
  await page.waitForSelector(LOGGED_IN, { timeout: 15000 });

  const server = await page.evaluate(async () => (await fetch("/api/version")).json());
  check("/api/version reports a commit and a version", typeof server.commit === "string" && typeof server.version === "string", JSON.stringify(server));
  check("the server is stamped (not 'unknown'), so the rest of this is a real check", server.commit !== "unknown" && server.version !== "unknown", JSON.stringify(server));
  const expectedLabel = `${server.version} (${server.commit.slice(0, 12)})`;

  // --- Help -> About --------------------------------------------------------
  const helpButton = page.locator('[data-testid^="rail-help"]').first();
  await helpButton.click();
  await page.click("button:has-text('About')");
  await page.waitForSelector('[data-testid="about-version"]', { timeout: 5000 });
  const shown = (await page.locator('[data-testid="about-version"]').textContent()).trim();
  check("Help -> About shows NexusQC <version> (<commit>) from the server", shown === `NexusQC ${expectedLabel}`, shown);

  await page.click('[data-testid="about-version-copy"]');
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  check("the copy button puts exactly the version string on the clipboard", copied === expectedLabel, copied);
  const copiedLabel = (await page.locator('[data-testid="about-version-copy"]').textContent()).trim();
  check("and says Copied", copiedLabel === "Copied", copiedLabel);

  const bugHref = await page.locator('[data-testid="about-bug-link"]').getAttribute("href");
  const featHref = await page.locator('[data-testid="about-feature-link"]').getAttribute("href");
  check("the About bug link opens the public bug form with the version prefilled",
    bugHref.startsWith(PUBLIC) && params(bugHref).get("template") === "bug_report.yml" && params(bugHref).get("version") === expectedLabel, bugHref);
  check("the About feature link opens the feature form with the version prefilled",
    featHref.startsWith(PUBLIC) && params(featHref).get("template") === "feature_request.yml" && params(featHref).get("version") === expectedLabel, featHref);
  for (const id of ["about-bug-link", "about-feature-link"]) {
    const target = await page.locator(`[data-testid="${id}"]`).getAttribute("target");
    check(`${id} opens in a new tab`, target === "_blank");
  }
  await page.screenshot({ path: "/tmp/gh_01_about.png" });
  await page.keyboard.press("Escape");

  // --- Bug-report flyout -----------------------------------------------------
  await openUserMenu(page);
  await page.click('[data-testid="bug-report-open"]');
  await page.waitForSelector('[data-testid="bug-report-body"]', { timeout: 5000 });
  const marker = "gh01 " + randSuffix(6);
  const text = `The orbital viewer shows nothing for job ${marker}`;
  await page.fill('[data-testid="bug-report-body"]', text);
  const ghHref = await page.locator('[data-testid="bug-report-github"]').getAttribute("href");
  check("Open on GitHub carries the typed text and the server version",
    ghHref.startsWith(PUBLIC) && params(ghHref).get("description") === text && params(ghHref).get("version") === expectedLabel, ghHref);
  await page.screenshot({ path: "/tmp/gh_01_flyout.png" });

  // File it for real, so the server's stamp can be read back.
  await page.click('[data-testid="bug-report-submit"]');
  await page.waitForSelector("text=your report was sent", { timeout: 10000 });
  await page.keyboard.press("Escape");

  // --- Admin inbox -------------------------------------------------------------
  // Through the same context: a second admin login elsewhere would end this
  // page's session (one live session per account), which is what logged the
  // first version of this spec out halfway through.
  const reports = await (await ctx.request.get(`${BASE_URL}/api/admin/bug-reports`)).json();
  const mine = reports.find((r) => r.body === text);
  check("the report is in the admin inbox", Boolean(mine));
  if (mine) {
    check("the server stamped the build it was running", mine.build_commit === server.commit && mine.build_version === server.version, `${mine.build_version} ${mine.build_commit}`);
    check("and the browser that filed it", typeof mine.user_agent === "string" && /Chrom|HeadlessChrome/i.test(mine.user_agent), mine.user_agent);

    await openUserMenu(page);
    await page.click('[data-testid="admin-open"]');
    await page.waitForSelector("text=Admin console", { timeout: 10000 });
    // The panel's badge query re-renders the nav once the report count lands;
    // wait for the row's section to settle before clicking into it.
    await page.waitForSelector('[data-testid="admin-nav-reports"]', { timeout: 10000 });
    await page.waitForTimeout(1000);
    await page.click('[data-testid="admin-nav-reports"]');
    await page.waitForSelector(`[data-testid="admin-report-row-${mine.id}"]`, { timeout: 10000 });
    await page.click(`[data-testid="admin-report-row-${mine.id}"]`);
    await page.waitForSelector('[data-testid="admin-report-github"]', { timeout: 5000 });
    const build = (await page.locator('[data-testid="admin-report-build"]').textContent()).trim();
    check("the inbox shows the build the report was filed against", build === expectedLabel, build);
    const fileHref = await page.locator('[data-testid="admin-report-github"]').getAttribute("href");
    check("File on GitHub prefills the form with the report and its build",
      fileHref.startsWith(PUBLIC) && params(fileHref).get("description") === text && params(fileHref).get("version") === expectedLabel, fileHref);
    await page.screenshot({ path: "/tmp/gh_01_admin.png" });

  }

  check("nothing navigated to github.com", !page.url().includes("github.com"), page.url());
  return { ctx, browser, text };
}

// Cleanup runs whether the checks passed or a wait timed out halfway: an
// earlier version of this spec left one report per crashed run in the inbox.
let handle = null;
main()
  .then((h) => { handle = h; })
  .catch((e) => { console.error(e); })
  .finally(async () => {
    let ok = false;
    try {
      if (handle) {
        const { ctx, text } = handle;
        const reports = await (await ctx.request.get(`${BASE_URL}/api/admin/bug-reports`)).json();
        for (const r of reports.filter((r) => r.body === text)) {
          const del = await ctx.request.delete(`${BASE_URL}/api/admin/bug-reports/${r.id}`, { headers: { Origin: BASE_URL } });
          check("the test's report is deleted afterwards", del.status() === 204, `${del.status()}`);
        }
        await handle.browser.close();
      }
    } finally {
      ok = summary();
      process.exit(ok ? 0 : 1);
    }
  });
