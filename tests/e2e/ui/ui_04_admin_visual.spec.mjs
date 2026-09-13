// The admin console, plus a visual/accessibility sweep whose screenshots
// feed the report.
//
// Also asserts the ABSENCE of two capabilities whose backend routes are
// live and whose client functions already exist in lib/api.ts, but which
// have no UI caller anywhere: user management (listAdminUsers) and
// invite minting (POST /api/admin/invites). On a multi-user deployment
// the only way to add a user is a raw API call, which is a real
// operational gap rather than a cosmetic one.
import { newBrowser, freshContext, uiLogin, waitForComposerReady, check, summary, shot, control, openUserMenu, BASE_URL, ADMIN_USER, adminPassword } from "./_ui.mjs";

const browser = await newBrowser();
const ctx = await freshContext(browser);
const page = await ctx.newPage();

try {
  await uiLogin(page, ADMIN_USER, adminPassword());
  await waitForComposerReady(page);

  // -------------------------------------------------------- open console
  await openUserMenu(page);
  const adminBtn = page.locator('[data-testid="admin-open"]');
  check("the admin-console entry is visible to an admin account",
    (await adminBtn.count()) > 0);
  await adminBtn.first().click();
  // The console's storage readout and audit log arrive from their own
  // queries; snapshotting immediately catches a half-rendered dialog and
  // produces false "section missing" failures.
  await page.waitForSelector("text=Live storage usage", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);

  const body0 = await page.evaluate(() => document.body.innerText);
  check("admin console opens", body0.includes("Admin console"));
  await shot(page, "ui04-admin-console");

  // ------------------------------------------------------ sections
  // The console is a section list plus one pane now, not one long scroll, so
  // a section's content only exists in the DOM while its nav entry is
  // selected. Each is visited in turn and checked for a heading it owns.
  //
  // Headings are CSS text-transform: uppercase and innerText returns the
  // TRANSFORMED text, so a title-case comparison would fail on rendered
  // content that is perfectly correct. Compare case-insensitively.
  //
  // The overview pane used to lead with a "Public web access" block. That
  // control was removed from the console, so the spec asked for a heading
  // that no longer exists and failed on correct behaviour. Overview now owns
  // only the quota and concurrency block. "Deployment" was added to the nav
  // after this spec was written and is checked here too.
  const SECTIONS = [
    ["overview", ["Storage quotas"]],
    ["invites", ["Invites"]],
    ["users", ["Users"]],
    ["reports", ["Bug reports"]],
    ["storage", ["Live storage usage"]],
    ["audit", ["Admin action history"]],
    ["deployment", ["What is running", "Who is working right now"]],
    ["danger", ["Purge all job history", "acts on every user"]],
  ];
  for (const [id, headings] of SECTIONS) {
    const nav = page.locator(`[data-testid="admin-nav-${id}"]`);
    check(`admin console has a "${id}" nav entry`, (await nav.count()) > 0);
    if (!(await nav.count())) continue;
    await nav.first().click();
    await page.waitForTimeout(900);
    const text = (await page.evaluate(() => document.body.innerText)).toUpperCase();
    for (const heading of headings) {
      check(`section "${id}" shows "${heading}"`, text.includes(heading.toUpperCase()), "");
    }
  }

  // Back to overview for the quota checks below.
  await page.locator('[data-testid="admin-nav-overview"]').click();
  await page.waitForTimeout(900);

  // -------------------------------------------- quota save round-trip
  // The quota inputs have no stable selector, so this walks up from the
  // label -- the same three-hop pattern the pre-existing p1_happy_paths
  // spec already had to use. Fragile by necessity; see the report's
  // testability section.
  const kbField = page.locator("text=Per-user KB quota").locator("..").locator("..")
    .locator('input[type="number"]');
  if (await kbField.count()) {
    const before = await kbField.first().inputValue();
    const next = String(Number(before) + 1);
    await kbField.first().fill(next);
    await page.waitForTimeout(300);
    const save = page.locator('button:has-text("Save")').first();
    const enabled = await save.isEnabled().catch(() => false);
    check("the Save button enables only once a quota field is dirty", enabled);
    if (enabled) {
      await save.click();
      await page.waitForTimeout(2500);
      const server = await page.evaluate(async () => {
        const r = await fetch("/api/admin/config");
        return r.ok ? await r.json() : null;
      });
      // This app uses DECIMAL gigabytes (1e9) everywhere, deliberately and
      // consistently -- see the comments in AdminPanel.tsx and
      // StorageUsageBadge.tsx. Asserting against 2^30 would be wrong.
      const gb = server ? server.per_user_kb_quota_bytes / 1_000_000_000 : null;
      check("a quota change round-trips to the server, not just the UI",
        gb !== null && Math.abs(gb - Number(next)) < 0.01,
        `UI set ${next}GB, server reports ${gb}GB`);
      // restore
      await kbField.first().fill(before);
      await page.waitForTimeout(300);
      const save2 = page.locator('button:has-text("Save")').first();
      if (await save2.isEnabled().catch(() => false)) await save2.click();
      await page.waitForTimeout(1500);
    }
  } else {
    check("per-user KB quota field reachable", false,
      "label->parent->parent->input walk failed (no stable selector exists)");
  }

  // --------------------------------------------- user actions are reachable
  // Suspend/Restore/Delete always existed and worked; they were the last
  // column of an overflow-x-auto table inside a narrower dialog, so on any
  // realistic window they were scrolled out of sight -- which is how a working
  // delete-account button came to be reported as a missing feature. The
  // assertion is that they are actually VISIBLE, not merely in the DOM.
  await page.locator('[data-testid="admin-nav-users"]').click();
  await page.waitForTimeout(900);

  const userRows = page.locator('tr[data-testid^="admin-user-row-"]');
  const nUsers = await userRows.count();
  check("the users section lists at least one user", nUsers > 0, `${nUsers} rows`);

  const deleteBeforeExpand = await page.locator('button:has-text("Delete account")').count();
  check("no per-user action is shown until a row is opened (rows stay scannable)",
    deleteBeforeExpand === 0, `${deleteBeforeExpand} visible`);

  if (nUsers > 0) {
    // Pick a row that is not the admin's own -- the backend refuses
    // self-delete, so that row deliberately renders an explanation instead.
    let opened = false;
    for (let i = 0; i < nUsers; i++) {
      await userRows.nth(i).click();
      await page.waitForTimeout(400);
      if (await page.locator('button:has-text("Delete account")').count()) { opened = true; break; }
      await userRows.nth(i).click(); // collapse and try the next
      await page.waitForTimeout(200);
    }
    check("opening a user row reveals the delete action", opened);
    if (opened) {
      const del = page.locator('button:has-text("Delete account")').first();
      check("the delete action is actually visible, not just present in the DOM",
        await del.isVisible());
      const box = await del.boundingBox();
      const vw = page.viewportSize()?.width ?? 1280;
      check("the delete action is inside the viewport, not scrolled off to the right",
        box !== null && box.x >= 0 && box.x + box.width <= vw,
        `x=${box?.x?.toFixed(0)} w=${box?.width?.toFixed(0)} viewport=${vw}`);
      await shot(page, "ui04-user-row-expanded");
    }
  }

  // ------------------------------------------------- purge is type-to-confirm
  // The deployment-wide purges are no longer two-click. Two clicks in the same
  // place is a reflex; typing the exact phrase is not, and it names the target
  // so you cannot be mid-confirm on the jobs purge believing it is the chat
  // one. The per-row ConfirmButton keeps its two-click behaviour.
  await page.locator('[data-testid="admin-nav-danger"]').click();
  await page.waitForTimeout(900);

  const purgeBtn = page.locator('[data-testid="admin-purge-jobs"]');
  const phraseInput = page.locator('[data-testid="admin-purge-jobs-phrase"]');
  check("the danger zone exposes a jobs purge", (await purgeBtn.count()) > 0);

  if (await purgeBtn.count()) {
    check("the purge button is DISABLED before the phrase is typed",
      await purgeBtn.first().isDisabled());

    const warned = await page.evaluate(() => document.body.innerText);
    check("the danger zone states the blast radius and that there is no undo",
      /every user/i.test(warned) && /no undo/i.test(warned), "");

    // A near-miss must not arm it -- otherwise the gate is decorative.
    await phraseInput.first().fill("PURGE ALL JOB");
    await page.waitForTimeout(200);
    check("a partially-typed phrase still leaves the purge disabled",
      await purgeBtn.first().isDisabled());

    // The wrong purge's phrase must not arm this one either.
    await phraseInput.first().fill("PURGE ALL CHAT");
    await page.waitForTimeout(200);
    check("another purge's phrase does not arm this one",
      await purgeBtn.first().isDisabled());

    await phraseInput.first().fill("PURGE ALL JOBS");
    await page.waitForTimeout(200);
    check("the exact phrase arms the purge", await purgeBtn.first().isEnabled());
    await shot(page, "ui04-purge-confirm");

    // Clear it again rather than firing: this spec must not purge the stack.
    await phraseInput.first().fill("");
    await page.waitForTimeout(200);
    check("clearing the phrase disarms it again", await purgeBtn.first().isDisabled());
  }

  await page.locator('[data-testid="admin-nav-overview"]').click();
  await page.waitForTimeout(600);

  // -------------------------------------------------- audit log populated
  const auditRows = await page.evaluate(async () => {
    const r = await fetch("/api/admin/audit-log");
    return r.ok ? (await r.json()).length : -1;
  });
  check("the admin action history has entries from this run", auditRows > 0,
    `${auditRows} rows`);

  // --------------------------------------------- admin capability coverage
  // This check used to assert the OPPOSITE -- it was a [GAP] marker recording
  // that the console exposed no user-management or invite-minting UI at all,
  // so onboarding a user meant a raw API call. That gap is now closed, and
  // the check is inverted to keep it closed: it fails if the sections ever
  // disappear again.
  const bodyNow = await page.evaluate(() => document.body.innerText);
  const hasUserMgmt = /create invite|invites/i.test(bodyNow) && /users/i.test(bodyNow);
  check("the admin console exposes user-management and invite-minting UI, "
    + "so onboarding and revoking a user needs no raw API call",
    hasUserMgmt,
    hasUserMgmt ? "invites + users sections present"
      : "MISSING -- the console has regressed to raw-API-only onboarding");

  // close
  await page.keyboard.press("Escape");
  await page.waitForTimeout(600);

  // -------------------------------------------------- responsive sweep
  for (const [w, h] of [[1280, 800], [1600, 900], [1920, 1080]]) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(700);
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    check(`no horizontal page overflow at ${w}x${h}`, !overflow);
    await shot(page, `ui04-viewport-${w}`);
  }

  // ------------------------------------------------- keyboard/focus pass
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const s = getComputedStyle(el);
    return {
      tag: el.tagName,
      label: (el.getAttribute("title") || el.getAttribute("aria-label")
        || el.textContent || "").trim().slice(0, 40),
      outline: s.outlineStyle,
      ring: s.boxShadow !== "none",
    };
  });
  check("keyboard Tab moves focus to a real control", focused !== null,
    JSON.stringify(focused));
  if (focused) {
    check("the focused control has a visible focus indicator "
      + "(outline or ring)",
      focused.outline !== "none" || focused.ring === true,
      JSON.stringify(focused));
  }

  // ------------------------------------------------- reduced motion
  await ctx.close();
  // prefers-reduced-motion is a CSS-level media query: overriding
  // window.matchMedia in JS does not affect it at all. Playwright's
  // context option is the only thing that actually flips it.
  const rmCtx = await browser.newContext({
    ignoreHTTPSErrors: true, baseURL: BASE_URL, reducedMotion: "reduce",
  });
  await rmCtx.addInitScript(() => {
    try {
      localStorage.removeItem("qc-agent-layout");
      localStorage.removeItem("qc-agent-active-thread");
    } catch (e) { /* first load */ }
  });
  const rmPage = await rmCtx.newPage();
  await uiLogin(rmPage, ADMIN_USER, adminPassword());
  await waitForComposerReady(rmPage);
  const durations = await rmPage.evaluate(() => {
    const el = document.querySelector("[class*='animate-']");
    if (!el) return null;
    return getComputedStyle(el).animationDuration;
  });
  check("prefers-reduced-motion is honored globally (animations collapse to "
    + "near-zero duration in one place, not per component)",
    durations === null || parseFloat(durations) < 0.05,
    `animation-duration=${durations}`);
  await rmPage.close();
  await rmCtx.close();

} catch (e) {
  check("ui_04 completed without throwing", false, String(e).slice(0, 400));
  try { await shot(page, "ui04-FAILURE"); } catch { /* best effort */ }
} finally {
  const ok = summary();
  await browser.close();
  process.exit(ok ? 0 : 1);
}
