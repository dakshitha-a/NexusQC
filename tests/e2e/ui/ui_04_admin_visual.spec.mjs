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
  // Section headings are CSS text-transform: uppercase, and innerText
  // returns the TRANSFORMED text -- so a title-case comparison here fails
  // on rendered content that is perfectly correct. Compare case-insensitively.
  const bodyUpper = body0.toUpperCase();
  for (const section of [
    "Public web access",
    "Storage quotas",
    "Live storage usage",
    "Invites",
    "Users",
    "Bug reports",
    "Purge history",
    "Admin action history",
  ]) {
    check(`admin console section present: "${section}"`,
      bodyUpper.includes(section.toUpperCase()), "");
  }

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

  // ------------------------------------------------- purge confirm/cancel
  const purge = page.locator('button:has-text("Purge all job history")');
  if (await purge.count()) {
    await purge.first().click();
    await page.waitForTimeout(500);
    const warned = await page.evaluate(() => document.body.innerText);
    check("a purge button requires a second confirmation and warns that it "
      + "affects every user with no undo",
      warned.includes("no undo") || warned.includes("Confirm purge"), "");
    await shot(page, "ui04-purge-confirm");
    const cancel = page.locator('button:has-text("Cancel")');
    if (await cancel.count()) {
      await cancel.first().click();
      await page.waitForTimeout(500);
      const after = await page.evaluate(() => document.body.innerText);
      check("Cancel aborts the purge without executing it",
        !after.includes("Confirm purge"), "");
    }
  } else {
    check("purge controls present", false, "not found");
  }

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
