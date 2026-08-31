/**
 * The instrument panel scrolls its own content, and never scrolls the app.
 *
 * The bug this pins: with the Molecule pane open and the panes below it
 * expanded, the instrument panel's content was taller than the panel, and
 * the overflow escaped it. ShellLayout's three-panel row sets
 * overflow-x-auto, and CSS computes the other axis to `auto` whenever one
 * axis is not `visible`, so that row had quietly become vertically
 * scrollable too. The result was that scrolling moved the WHOLE row: the
 * sidebar and the chat pane were dragged up out of the viewport and left a
 * black band along the bottom of the window. Closing the Molecule pane made
 * it go away, because that pane is the tall one.
 *
 * Every one of those numbers is a layout fact, so a code read cannot settle
 * any of it, and neither can a screenshot. This measures instead:
 * scrollHeight against clientHeight on the row, and where the sidebar's
 * bottom edge actually lands after an attempt to scroll.
 *
 * The molecule is placed through POST /api/threads/{id}/molecule/build,
 * which turns a molblock into a frame without an LLM turn -- the viewer
 * only takes its real ~350px once something is in it, and a chat turn would
 * make this spec slow and depend on the model for a layout measurement.
 *
 * Raw Playwright, chromium, headless -- no @playwright/test runner, same
 * convention as the rest of tests/frontend.
 *
 *   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
 *     node tests/frontend/ui_08_dock_overflow.spec.mjs
 */
import {
  BASE_URL, adminApiLogin, check, deleteUserByUsername, mintInvite,
  newBrowser, newContext, summary,
} from "./_helpers.mjs";

const WATER_MOLBLOCK = `
     RDKit          3D

  3  2  0  0  0  0  0  0  0  0999 V2000
   -0.0003    0.3978    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
   -0.7633   -0.1996    0.0000 H   0  0  0  0  0  0  0  0  0  0  0  0
    0.7636   -0.1983    0.0000 H   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0
  1  3  1  0
M  END
`;

/** Everything this spec needs to know about the layout, in one pass. */
async function layout(page) {
  return page.evaluate(() => {
    const row = document.querySelector("div.relative.flex.min-h-0");
    const dock = document
      .querySelector('[data-testid="shell-collapse-panel"]')
      .closest("div.flex.min-w-0.shrink-0.flex-col");
    const scroller = dock.querySelector("div.overflow-y-auto");
    const rail = document.querySelector('[title="Collapse sidebar"]')
      .closest("div.flex.min-w-0.shrink-0.flex-col");
    const jmToggle = document.querySelector('[data-testid="section-job-manager-all-jobs-toggle"]');
    return {
      viewportH: document.documentElement.clientHeight,
      rowOverflowsBy: row.scrollHeight - row.clientHeight,
      rowOverflowY: getComputedStyle(row).overflowY,
      railBottom: Math.round(rail.getBoundingClientRect().bottom),
      dockScrollsBy: scroller ? scroller.scrollHeight - scroller.clientHeight : null,
      jobManagerH: jmToggle
        ? Math.round(jmToggle.closest("div.flex.flex-1.flex-col").getBoundingClientRect().height)
        : null,
      moleculeVisible: !!document.querySelector("canvas"),
    };
  });
}

/** Tries to scroll the three-panel row, and reports where the sidebar
 *  ended up. Before the fix this moved the sidebar up by the overflow. */
async function tryScrollingTheRow(page) {
  await page.evaluate(() => {
    document.querySelector("div.relative.flex.min-h-0").scrollTop = 9999;
  });
  await page.waitForTimeout(300);
  return layout(page);
}

async function main() {
  const browser = await newBrowser();
  const adminCtx = await newContext(browser);
  await adminApiLogin(adminCtx);
  const token = await mintInvite(adminCtx, "user");
  const username = "qatest_dockoverflow_" + Math.random().toString(36).slice(2, 8);
  const password = "correct horse battery staple 1";

  const ctx = await newContext(browser);
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1400, height: 900 });
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 200)));
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
  });

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
    consoleErrors.length = 0;
    check("registered and logged in", true);

    console.log("\n== put a molecule in the panel and open every dock section ==");
    const threads = await (await page.request.get(`${BASE_URL}/api/threads`)).json();
    const threadId = threads[0].thread_id;
    const built = await page.request.post(`${BASE_URL}/api/threads/${threadId}/molecule/build`, {
      headers: { Origin: BASE_URL },
      data: { molblock: WATER_MOLBLOCK, charge: 0, multiplicity: 1 },
    });
    check("a molecule can be placed without an LLM turn", built.status() === 200,
          `${built.status()} ${(await built.text()).slice(0, 150)}`);
    await page.evaluate(() => {
      const raw = localStorage.getItem("qc-agent-layout");
      const p = raw ? JSON.parse(raw) : { state: {}, version: 0 };
      p.state = {
        ...p.state, moleculeCollapsed: false, jobsCollapsed: false,
        plotsCollapsed: false, jobManagerCollapsed: false,
      };
      localStorage.setItem("qc-agent-layout", JSON.stringify(p));
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector("canvas", { timeout: 30000 });
    await page.waitForTimeout(1200);
    check("the 3D viewer is rendered, so the Molecule pane is at its real height",
          (await layout(page)).moleculeVisible);

    console.log("\n== with room to spare, nothing scrolls and the panel flexes ==");
    let m = await layout(page);
    check("the row does not overflow at 900px", m.rowOverflowsBy === 0, JSON.stringify(m));
    check("the dock does not need to scroll either", m.dockScrollsBy === 0, JSON.stringify(m));
    const roomyJobManager = m.jobManagerH;
    check("and the Job manager has taken the leftover space", roomyJobManager > 200,
          `job manager is ${roomyJobManager}px`);

    console.log("\n== on a short window, the DOCK scrolls, not the app ==");
    for (const height of [600, 520, 450]) {
      await page.setViewportSize({ width: 1400, height });
      await page.waitForTimeout(600);
      m = await layout(page);
      check(`at ${height}px the row still does not overflow`, m.rowOverflowsBy === 0,
            JSON.stringify(m));
      check(`at ${height}px the dock scrolls its own content instead`, m.dockScrollsBy > 0,
            JSON.stringify(m));
      check(`at ${height}px the Job manager keeps a usable height rather than vanishing`,
            m.jobManagerH >= 140, `job manager is ${m.jobManagerH}px`);
    }

    console.log("\n== and the row cannot be scrolled, which is the artifact itself ==");
    m = await tryScrollingTheRow(page);
    check("the sidebar's bottom edge is still the bottom of the window",
          m.railBottom === m.viewportH,
          `sidebar ends at ${m.railBottom}px in a ${m.viewportH}px window -- `
          + "the gap below it is the black band this test exists to prevent");
    check("the row's vertical overflow is pinned rather than left to compute to auto",
          m.rowOverflowY === "hidden", `overflow-y is ${m.rowOverflowY}`);

    console.log("\n== the bottom of the dock is reachable, not clipped ==");
    const reached = await page.evaluate(() => {
      const dock = document.querySelector('[data-testid="shell-collapse-panel"]')
        .closest("div.flex.min-w-0.shrink-0.flex-col");
      const s = dock.querySelector("div.overflow-y-auto");
      s.scrollTop = s.scrollHeight;
      return { top: Math.round(s.scrollTop), max: Math.round(s.scrollHeight - s.clientHeight) };
    });
    check("scrolling the dock reaches its last pixel", reached.top === reached.max && reached.max > 0,
          JSON.stringify(reached),
          );
    check("the Job manager's own controls are reachable there",
          await page.locator('[data-testid="section-job-manager-all-jobs-panel"]').isVisible());

    console.log("\n== closing the Molecule pane, which is what used to hide the bug ==");
    await page.click('[data-testid="section-molecule-toggle"]');
    await page.waitForTimeout(600);
    m = await layout(page);
    check("still no row overflow with the tall pane closed", m.rowOverflowsBy === 0, JSON.stringify(m));
    check("and the Job manager takes the space back", m.jobManagerH > 140,
          `job manager is ${m.jobManagerH}px`);

    console.log("\n== back to a tall window ==");
    await page.setViewportSize({ width: 1400, height: 900 });
    await page.click('[data-testid="section-molecule-toggle"]');
    await page.waitForTimeout(800);
    m = await layout(page);
    check("the dock stops scrolling once there is room again", m.dockScrollsBy === 0,
          JSON.stringify(m));
    check("and the Job manager is back to its roomy height", m.jobManagerH > 200,
          `job manager is ${m.jobManagerH}px`);

    check("no console or page errors during the whole run",
          consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
  } catch (err) {
    check("the run completed without throwing", false, String(err).slice(0, 400));
    try {
      console.log("  page text was:\n" + (await page.innerText("body")).slice(0, 900));
    } catch {}
  } finally {
    await deleteUserByUsername(adminCtx, username);
    await browser.close();
  }

  process.exit(summary() ? 0 : 1);
}

main();
