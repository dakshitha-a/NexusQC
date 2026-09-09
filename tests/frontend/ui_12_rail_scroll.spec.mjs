#!/usr/bin/env node
// The sidebar keeps its other four sections reachable however many
// conversations there are.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/ui_12_rail_scroll.spec.mjs
//
// The bug: the conversation list had no height cap and no scroll container of
// its own, inside a sidebar whose single overflow-y-auto wrapped all five
// sections at once. So a long list simply grew, and the Knowledge base, Files,
// Projects and Shared-with-me headers were pushed off the bottom of the
// screen. Around a dozen conversations was enough at the default text size,
// and about five at the largest. There was no way back to those sections
// except deleting conversations or collapsing the whole sidebar.
//
// This seeds enough conversations to have caused that, then requires the four
// headers to still be inside the viewport and the conversation list itself to
// be the thing that scrolls. It checks at the largest text size too, since
// that is where the old layout failed soonest and it is now a setting anyone
// can turn on.
//
// Every thread it creates is deleted at the end, including on failure. This
// suite does not do blind purges: it removes what it made and nothing else.
import {
  BASE_URL,
  ADMIN_USER,
  adminPassword,
  newBrowser,
  newContext,
  LOGGED_IN,
  randSuffix,
  check,
  summary,
} from "./_helpers.mjs";

const SEEDED = 26;
const SECTIONS = ["knowledge-base", "files", "projects"];
const created = [];

const browser = await newBrowser();
const ctx = await newContext(browser);
const page = await ctx.newPage();
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
await page.fill('input[type="password"]', adminPassword());
await page.click('[data-testid="auth-submit"]');
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });

try {
  const tag = randSuffix(6);
  for (let i = 0; i < SEEDED; i++) {
    const res = await page.request.post(`${BASE_URL}/api/threads`, {
      data: { label: `qatest_rail_${tag}_${String(i).padStart(2, "0")}` },
      headers: { Origin: BASE_URL },
    });
    created.push((await res.json()).thread_id);
  }

  for (const fontScale of [1, 1.35]) {
    await page.evaluate((fs) => {
      window.localStorage.setItem(
        "qc-agent-appearance",
        JSON.stringify({
          state: { theme: "balmer", accent: "hbeta", fontScale: fs, density: "cosy", motion: "full" },
          version: 0,
        }),
      );
    }, fontScale);
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForSelector('[data-testid="conversation-list"]', { timeout: 15000 });
    await page.waitForTimeout(500);

    const label = `at text scale ${fontScale}`;

    const scroll = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="conversation-scroll"]');
      return el ? { scrollH: el.scrollHeight, clientH: el.clientHeight } : null;
    });
    check(
      `${label}: the conversation list is the thing that scrolls`,
      scroll && scroll.scrollH > scroll.clientH,
      scroll ? `scrollHeight ${scroll.scrollH} > clientHeight ${scroll.clientH}` : "no scroll container",
    );

    for (const section of SECTIONS) {
      const box = await page.locator(`[data-testid="section-${section}-toggle"]`).boundingBox();
      const inView = box !== null && box.y >= 0 && box.y + box.height <= 900;
      check(
        `${label}: the ${section.replace("-", " ")} header is still on screen`,
        inView,
        box ? `y=${Math.round(box.y)} h=${Math.round(box.height)} viewport 900` : "not rendered",
      );
    }

    // The seeded conversations are all findable without scrolling, which is
    // what the filter is for now that the list is bounded.
    await page.click('[data-testid="conversation-search-open"]');
    await page.fill('[data-testid="conversation-search"]', "qatest_rail");
    await page.waitForTimeout(250);
    const shownCount = await page.locator('[data-testid^="conversation-row-"]').count();
    check(`${label}: the filter narrows the list`, shownCount === SEEDED, `${shownCount} rows, expected ${SEEDED}`);
    await page.fill('[data-testid="conversation-search"]', "zzzz-no-such-conversation");
    await page.waitForTimeout(250);
    check(
      `${label}: and says so when nothing matches`,
      await page.locator('[data-testid="conversation-empty"]').isVisible(),
    );
    await page.click('[data-testid="conversation-search-clear"]');
  }
} finally {
  for (const id of created) {
    await page.request.delete(`${BASE_URL}/api/threads/${id}`, { headers: { Origin: BASE_URL } }).catch(() => {});
  }
  console.log(`\ncleaned up ${created.length} seeded conversations`);
  await ctx.close();
  await browser.close();
}

process.exit(summary() ? 0 : 1);
