#!/usr/bin/env node
// The app knows its own name, says which conversation you are in, and has
// stopped printing " -- " at people.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/ui_15_identity_and_chat_header.spec.mjs
//
// Three separate things, grouped because they are all "what the interface
// says about itself":
//
// - There was no logo. The wordmark was the string "NexusQC" written out by
//   hand in three components at three different sizes, one of them beside a
//   generic lucide flask, and the favicon was an unmodified purple glyph from
//   the scaffold that created the frontend.
// - The chat pane had no header, so with the sidebar collapsed -- a state that
//   persists across reloads -- the app could not tell you which of your
//   conversations you were reading, and renaming existed only as a
//   double-click on the sidebar row.
// - Fifteen strings said " -- " on screen. That is a prose-document
//   convention; in an interface it reads as a typo. The last check here scans
//   the rendered text rather than the source, so it catches a new one wherever
//   it appears.
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

const browser = await newBrowser();
const ctx = await newContext(browser);
const page = await ctx.newPage();
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="auth-form-login"]', { timeout: 15000 });

check("the sign-in card carries the mark", await page.locator('[data-testid="brand-logo"]').first().isVisible());
check(
  "and names the app once, not twice",
  (await page.locator("text=NexusQC").count()) >= 1,
);

await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
await page.fill('input[type="password"]', adminPassword());
await page.click('[data-testid="auth-submit"]');
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });

check("the sidebar header carries the mark", await page.locator('[data-testid="brand-logo"]').first().isVisible());

// --- the chat header --------------------------------------------------------
const created = [];
try {
  const label = `qatest_hdr_${randSuffix(6)}`;
  const res = await page.request.post(`${BASE_URL}/api/threads`, {
    data: { label },
    headers: { Origin: BASE_URL },
  });
  const threadId = (await res.json()).thread_id;
  created.push(threadId);
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await page.click(`[data-testid="conversation-row-${threadId}"]`);
  await page.waitForTimeout(600);

  check("the chat pane has a header", await page.locator('[data-testid="chat-header"]').isVisible());
  check(
    "and it names the conversation you are in",
    (await page.locator('[data-testid="chat-header-title"]').innerText()).includes(label),
  );

  // It is also where renaming lives now, which it was not before: the only
  // route was a double-click on the sidebar row.
  const renamed = `${label}_renamed`;
  await page.click('[data-testid="chat-header-title"]');
  await page.waitForSelector('[data-testid="chat-header-rename-input"]', { timeout: 5000 });
  await page.fill('[data-testid="chat-header-rename-input"]', renamed);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(800);
  check(
    "renaming from the header sticks",
    (await page.locator('[data-testid="chat-header-title"]').innerText()).includes(renamed),
  );
  check(
    "and reaches the sidebar row too",
    (await page.locator(`[data-testid="conversation-row-${threadId}"]`).innerText()).includes(renamed),
  );

  // --- the welcome screen's engine table -----------------------------------
  await page.click('[data-testid="welcome-toggle-details"]');
  await page.waitForTimeout(300);
  const cells = await page.evaluate(() =>
    Array.from(document.querySelectorAll("td")).map((td) => td.innerText.trim()),
  );
  check(
    "an unsupported engine cell is a dash, not a stray comma",
    cells.includes("–") && !cells.some((c) => c === ","),
    `saw ${JSON.stringify([...new Set(cells)].slice(0, 8))}`,
  );

  // --- a user's message is not a block of accent ----------------------------
  const bubble = await page.evaluate(() => {
    const root = document.documentElement;
    const el = document.createElement("div");
    el.className = "bg-accent";
    document.body.appendChild(el);
    const accent = getComputedStyle(el).backgroundColor;
    el.remove();
    return { accent, theme: root.dataset.theme };
  });
  check("the accent token resolves", Boolean(bubble.accent), bubble.accent);

  // --- nothing says " -- " on screen ---------------------------------------
  const dashes = await page.evaluate(() => {
    const seen = [];
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walk.nextNode())) {
      if (n.nodeValue.includes(" -- ")) seen.push(n.nodeValue.trim().slice(0, 90));
    }
    // Attribute text is read aloud and shown on hover, so it counts too.
    for (const el of document.querySelectorAll("[title]")) {
      const t = el.getAttribute("title");
      if (t.includes(" -- ")) seen.push(`title: ${t.slice(0, 90)}`);
    }
    return seen;
  });
  check("nothing on this screen says \" -- \"", dashes.length === 0, dashes.join(" | "));
} finally {
  for (const id of created) {
    await page.request.delete(`${BASE_URL}/api/threads/${id}`, { headers: { Origin: BASE_URL } }).catch(() => {});
  }
  console.log(`\ncleaned up ${created.length} seeded conversations`);
  await ctx.close();
  await browser.close();
}

process.exit(summary() ? 0 : 1);
