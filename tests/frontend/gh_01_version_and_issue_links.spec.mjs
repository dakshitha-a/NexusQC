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
import { newBrowser, newContext, adminApiLogin, adminPassword, ADMIN_USER, check, summary, LOGGED_IN, BASE_URL, openUserMenu, randSuffix } from "./_helpers.mjs";

const PUBLIC = "https://github.com/dakshitha-a/NexusQC/issues/new?";

function params(href) {
  return new URL(href).searchParams;
}

async function main() {
  const browser = await newBrowser();
  const ctx = await newContext(browser);
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: BASE_URL });
  const page = await ctx.newPage();
  await page.goto(BASE_URL);
  await page.waitForSelector('input[placeholder="Username"]', { timeout: 15000 });
  await page.fill('input[placeholder="Username"]', ADMIN_USER);
  await page.fill('input[placeholder="Password"]', adminPassword());
  await page.click('button[type="submit"]');
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
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const reports = await (await adminCtx.request.get(`${BASE_URL}/api/admin/bug-reports`)).json();
  const mine = reports.find((r) => r.body === text);
  check("the report is in the admin inbox", Boolean(mine));
  if (mine) {
    check("the server stamped the build it was running", mine.build_commit === server.commit && mine.build_version === server.version, `${mine.build_version} ${mine.build_commit}`);
    check("and the browser that filed it", typeof mine.user_agent === "string" && /Chrom|HeadlessChrome/i.test(mine.user_agent), mine.user_agent);

    await openUserMenu(page);
    await page.click('[data-testid="admin-open"]');
    await page.click('[data-testid="admin-nav-reports"]');
    await page.click(`[data-testid="admin-report-row-${mine.id}"]`);
    await page.waitForSelector('[data-testid="admin-report-github"]', { timeout: 5000 });
    const build = (await page.locator('[data-testid="admin-report-build"]').textContent()).trim();
    check("the inbox shows the build the report was filed against", build === expectedLabel, build);
    const fileHref = await page.locator('[data-testid="admin-report-github"]').getAttribute("href");
    check("File on GitHub prefills the form with the report and its build",
      fileHref.startsWith(PUBLIC) && params(fileHref).get("description") === text && params(fileHref).get("version") === expectedLabel, fileHref);
    await page.screenshot({ path: "/tmp/gh_01_admin.png" });

    const del = await adminCtx.request.delete(`${BASE_URL}/api/admin/bug-reports/${mine.id}`);
    check("the test's report is deleted afterwards", del.status() === 204, `${del.status()}`);
  }

  check("nothing navigated to github.com", !page.url().includes("github.com"), page.url());
  await browser.close();
  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
