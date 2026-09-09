/**
 * The Job Manager's search box, and that it is genuinely fuzzy.
 *
 * Fuzziness is the part worth asserting in a browser rather than trusting
 * to a code read, because it is the part that silently degrades: a
 * substring filter passes every test a fuzzy one does except the one that
 * distinguishes them. So the load-bearing case here is a query that is a
 * subsequence of the job's name but not a substring of it -- "wtr" against
 * "water ..." -- which a substring filter rejects and a fuzzy matcher
 * accepts.
 *
 * One real job is created through the chat rather than seeded, because the
 * name being searched has to be the name auto_job_name actually produced.
 *
 * Raw Playwright, chromium, headless -- no @playwright/test runner, same
 * convention as the rest of tests/frontend.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/jobs_01_search.spec.mjs
 */
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, summary,
} from "./_helpers.mjs";

const SEARCH = '[data-testid="jobmanager-search"]';
const EMPTY = '[data-testid="jobmanager-search-empty"]';

// The search box is an icon in the section header until it is asked for, and
// it opens as a row in the panel body. It used to be a permanent input, which
// cost a row of the app's only flex-1 pane whether or not anyone was
// searching. Everything below still drives the same input with the same
// testid; it just has to be opened first.
async function openSearch(page) {
  if ((await page.locator(SEARCH).count()) === 0) {
    await page.click('[data-testid="jobmanager-search-open"]');
    await page.waitForSelector(SEARCH, { timeout: 5000 });
  }
}

async function send(page, text) {
  const box = page.locator("textarea").first();
  await box.fill(text);
  await box.press("Enter");
}

async function rowCount(page) {
  return page.locator('[data-testid^="jobmanager-row-"]').count();
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_jobsearch_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  const jobIds = [];

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

    console.log("\n== create one job so there is something to search ==");
    await send(page, "Run a single point energy calculation on water.");
    await page.waitForFunction(
      () => document.body.innerText.includes("level of theory")
         || document.body.innerText.includes("basis set"),
      undefined,
      { timeout: 180000 },
    );
    await send(page, "Use HF with the sto-3g basis.");
    await page.locator("text=/Approve .* job/").first().waitFor({ timeout: 240000 });
    await page.locator("button", { hasText: /^Approve/ }).first().click();
    await page.waitForFunction(
      () => /\bStarted\b/.test(document.body.innerText),
      undefined,
      { timeout: 60000 },
    );
    const line = ((await page.innerText("body")).split("\n")
      .find((l) => /\bStarted\b/.test(l)) || "").trim();
    const idMatch = line.match(/Job id\s+([0-9a-f]{6,})/i);
    if (idMatch) jobIds.push(idMatch[1]);
    check("a job exists to search for", jobIds.length > 0, line);

    console.log("\n== the search box is there, and the job is listed ==");
    await page.waitForSelector('[data-testid="jobmanager-search-open"]', { timeout: 30000 });
    await openSearch(page);
    check("the Job Manager has a search box", true);
    await page.waitForFunction(
      (sel) => document.querySelectorAll(sel).length > 0,
      '[data-testid^="jobmanager-row-"]',
      { timeout: 30000 },
    );
    const before = await rowCount(page);
    check(`the job list has ${before} row(s) before filtering`, before > 0);

    console.log("\n== an exact term still matches ==");
    await openSearch(page);
    await page.fill(SEARCH, "water");
    await page.waitForTimeout(200);
    check("searching the molecule keeps the job", await rowCount(page) > 0);

    console.log("\n== and a subsequence matches, which is the fuzzy part ==");
    // "wtr" is not a substring of "water SP HF/sto-3g (PYSCF)". It is a
    // subsequence. A substring filter fails this and a fuzzy one passes.
    await openSearch(page);
    await page.fill(SEARCH, "wtr");
    await page.waitForTimeout(200);
    check("a non-contiguous subsequence still matches", await rowCount(page) > 0,
          "fuzzy matching is not active -- this is what a substring filter fails");

    // Same idea against the level of theory rather than the molecule.
    await openSearch(page);
    await page.fill(SEARCH, "sto3g");
    await page.waitForTimeout(200);
    check("dropping a character from the basis still matches", await rowCount(page) > 0);

    console.log("\n== a query that matches nothing says so ==");
    await openSearch(page);
    await page.fill(SEARCH, "zzqqxx");
    await page.waitForTimeout(200);
    check("no rows survive a nonsense query", await rowCount(page) === 0);
    check("and the empty state explains why",
          await page.locator(EMPTY).count() > 0);

    console.log("\n== clearing restores the list ==");
    await page.click('[data-testid="jobmanager-search-clear"]');
    await page.waitForTimeout(200);
    check("the clear button empties the box",
          (await page.inputValue(SEARCH)) === "");
    check("and every row is back", await rowCount(page) === before);
  } catch (err) {
    check("the run completed without throwing", false, String(err).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 800));
    } catch {}
  } finally {
    for (const id of jobIds) {
      try {
        await page.request.delete(`${BASE_URL}/api/jobs/${id}`, { headers: { Origin: BASE_URL } });
      } catch {}
    }
    await deleteUserByUsername(adminCtx, username);
    await browser.close();
  }

  const ok = summary();
  process.exit(ok ? 0 : 1);
}

main();
