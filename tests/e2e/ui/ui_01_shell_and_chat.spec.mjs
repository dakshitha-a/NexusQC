// Shell layout, panel behavior, conversation management, and live chat
// streaming -- all of which had ZERO automated coverage before this pass
// (the five pre-existing specs under tests/frontend/ are auth/admin only).
//
// The streaming assertion is the interesting one. server/routes/chat.py
// streams real per-token deltas over SSE and the frontend appends them to
// an in-progress bubble by message_id, then reconciles against the
// authoritative final AIMessage. Asserting only "text eventually appears"
// would pass just as happily if the whole reply arrived as one blob, so
// this spec samples the bubble's length over time and requires it to grow
// in more than one step.
import { newBrowser, freshContext, uiLogin, waitForComposerReady, check, summary, shot, control, BASE_URL, ADMIN_USER, adminPassword } from "./_ui.mjs";

const browser = await newBrowser();
const ctx = await freshContext(browser);
const page = await ctx.newPage();

try {
  await uiLogin(page, ADMIN_USER, adminPassword());
  check("login through the real LoginScreen reaches the app shell", true);

  console.log("  [step] shell");
  // ---------------------------------------------------------------- shell
  await waitForComposerReady(page);

  for (const [title, back] of [
    ["Collapse sidebar", "Expand sidebar"],
    ["Collapse panel", "Expand panel"],
  ]) {
    const btn = control(page, title);
    if (!(await btn.count())) {
      check(`${title} control present`, false, "not found");
      continue;
    }
    // F-013: is this control actually reachable by a real click, or is
    // something painted on top of it? AccountBar is absolutely positioned
    // at top-2 right-2 with z-30 while RightDock's header is static, so
    // "Collapse panel" sits underneath the "Log out" button at every
    // viewport size -- the panel cannot be collapsed, and a click where it
    // appears logs the user out instead.
    const obstruction = await page.evaluate((t) => {
      const el = document.querySelector(`button[title="${t}"]`);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (!top || el.contains(top) || top === el) return null;
      return (top.getAttribute("title") || top.textContent || top.tagName).trim().slice(0, 40);
    }, title);
    check(`[F-013] "${title}" is not covered by another element`,
      obstruction === null,
      obstruction ? `covered by "${obstruction}" -- clicking it hits that instead` : "");
    if (obstruction !== null) continue;   // unreachable; do not hang for 30s

    await btn.first().click();
    await page.waitForTimeout(400);
    const restored = control(page, back);
    const ok = (await restored.count()) > 0;
    check(`${title} collapses and exposes "${back}"`, ok);
    if (ok) { await restored.first().click(); await page.waitForTimeout(400); }
  }

  console.log("  [step] layout-persistence");
  // Layout persistence: collapse, reload, and confirm it stuck.
  const collapse = control(page, "Collapse sidebar");
  if (await collapse.count()) {
    await collapse.first().click();
    await page.waitForTimeout(300);
    await page.reload();
    await waitForComposerReady(page);
    const stillCollapsed = (await control(page, "Expand sidebar").count()) > 0;
    check("panel collapse state persists across a reload (qc-agent-layout)", stillCollapsed);
    if (stillCollapsed) await control(page, "Expand sidebar").first().click();
  }

  console.log("  [step] resize-handle");
  // Keyboard-drivable resize -- the only keyboard-operable widget in the app.
  const handle = page.locator('[aria-label="Resize sidebar"]');
  if (await handle.count()) {
    const before = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("qc-agent-layout") || "{}"));
    await handle.first().focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(300);
    const after = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("qc-agent-layout") || "{}"));
    check("ResizeHandle responds to arrow keys (role=separator, tabIndex=0)",
      JSON.stringify(before) !== JSON.stringify(after),
      `${JSON.stringify(before)} -> ${JSON.stringify(after)}`);
  } else {
    check("ResizeHandle exposes aria-label", false, "not found");
  }

  console.log("  [step] help-flyout");
  // Help flyout
  const help = control(page, "Help");
  if (await help.count()) {
    await help.first().click();
    await page.waitForTimeout(500);
    const opened = await page.locator("text=Running a calculation").count();
    check("Help flyout opens and shows its documented sections", opened > 0);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
  } else {
    check("Help control present", false, "not found");
  }

  await shot(page, "ui01-shell");

  console.log("  [step] conversations");
  // -------------------------------------------------------- conversations
  const newConv = control(page, "New conversation");
  check("New conversation control present", (await newConv.count()) > 0);
  if (await newConv.count()) {
    await newConv.first().click();
    await waitForComposerReady(page);
    check("creating a conversation lands in a usable composer", true);
  }

  console.log("  [step] welcome");
  // --------------------------------------------------------- welcome copy
  const more = page.locator('button:has-text("More details")');
  if (await more.count()) {
    await more.first().click();
    await page.waitForTimeout(300);
    const table = await page.locator("text=PySCF").count();
    check("WelcomeMessage 'More details' reveals the engine capability table", table > 0);
  }

  console.log("  [step] streaming");
  // ------------------------------------------------------ token streaming
  await waitForComposerReady(page);
  await page.fill("textarea", "In two sentences, what is the Hartree-Fock method?");
  await page.click('[title="Send"]');

  // Sample the assistant bubble's text length over time.
  const samples = [];
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    const len = await page.evaluate(() => {
      const nodes = Array.from(document.querySelectorAll("div"))
        .filter((d) => d.className && String(d.className).includes("prose"));
      return nodes.length ? nodes[nodes.length - 1].innerText.length : 0;
    });
    samples.push(len);
    const done = await page.evaluate(() => {
      const ta = document.querySelector("textarea");
      return ta && !ta.disabled;
    });
    if (done && len > 0) break;
    await page.waitForTimeout(700);
  }
  const distinct = [...new Set(samples.filter((n) => n > 0))];
  check("assistant reply streamed token-by-token (bubble grew in >1 step, "
    + "not one buffered blob)",
    distinct.length > 1, `observed lengths: ${distinct.slice(0, 12).join(",")}`);
  check("assistant produced visible text", (distinct.at(-1) || 0) > 0,
    `final length ${distinct.at(-1) || 0}`);

  await shot(page, "ui01-chat-streamed");

  // ------------------------------------------------- agent step chips gone
  const chips = await page.locator("text=/running\\.\\.\\./").count();
  check("AgentStepChips clear once the turn completes", chips === 0, `${chips} still visible`);

} catch (e) {
  check("ui_01 completed without throwing", false, String(e).slice(0, 400));
  try { await shot(page, "ui01-FAILURE"); } catch { /* best effort */ }
} finally {
  const ok = summary();
  await browser.close();
  process.exit(ok ? 0 : 1);
}
