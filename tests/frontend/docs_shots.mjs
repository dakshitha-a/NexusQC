#!/usr/bin/env node
// Retakes the two screenshots the README leads with.
//
//   QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/docs_shots.mjs
//
// docs/screenshot.png is the app mid-approval: a conversation, the card
// showing the exact input file before anything runs, the 3D viewer and the job
// manager. It is driven through a real turn against the served model rather
// than staged, so it cannot show a state the app cannot actually reach.
//
// docs/screenshot-results.png is a finished job's detail drawer, which is the
// other half of the story and the part a screenshot of an empty app never
// tells.
//
// This exists because a redesign makes both stale, and a README whose picture
// does not match the app is worse than one with no picture. It creates one
// conversation and deletes it again.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { BASE_URL, ADMIN_USER, adminPassword, newBrowser, newContext, LOGGED_IN, randSuffix } from "./_helpers.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.resolve(HERE, "..", "..", "docs");
const PROMPT =
  process.env.QC_AGENT_SHOT_PROMPT ||
  "Run a single point energy on water with HF/STO-3G using PySCF";

const browser = await newBrowser();
const ctx = await newContext(browser);
const page = await ctx.newPage();
await page.setViewportSize({ width: 1600, height: 950 });
await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });
await page.fill('input[placeholder="Username or email"]', ADMIN_USER);
await page.fill('input[type="password"]', adminPassword());
await page.click('[data-testid="auth-submit"]');
await page.waitForSelector(LOGGED_IN, { timeout: 20000 });

const created = [];
try {
  const label = `qatest_shot_${randSuffix(6)}`;
  const res = await page.request.post(`${BASE_URL}/api/threads`, {
    data: { label },
    headers: { Origin: BASE_URL },
  });
  const threadId = (await res.json()).thread_id;
  created.push(threadId);
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await page.click(`[data-testid="conversation-row-${threadId}"]`);
  await page.waitForTimeout(800);

  const box = page.locator('[data-testid="chat-composer"]');
  await box.fill(PROMPT);
  await box.press("Enter");
  console.log("waiting for the approval card (a real agent turn, this takes a while)...");
  await page.waitForSelector('[data-testid="approval-approve"], [data-testid="job-approval-card"]', {
    timeout: 240000,
  });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(DOCS, "screenshot.png") });
  console.log("wrote docs/screenshot.png");

  // Decline it: this is a screenshot run, not a queue of work for somebody.
  const reject = page.locator('[data-testid="approval-reject"]');
  if (await reject.count()) {
    await reject.click();
    await page.waitForTimeout(1500);
  }
} finally {
  for (const id of created) {
    await page.request.delete(`${BASE_URL}/api/threads/${id}`, { headers: { Origin: BASE_URL } }).catch(() => {});
  }
  console.log(`cleaned up ${created.length} seeded conversations`);
}

// The results half: open whichever completed job the stack already has.
try {
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await page.waitForTimeout(1500);
  const row = page.locator('[data-testid^="jobmanager-row-"]').first();
  if (await row.count()) {
    await row.click();
    await page.waitForTimeout(3500);
    await page.screenshot({ path: path.join(DOCS, "screenshot-results.png") });
    console.log("wrote docs/screenshot-results.png");
  } else {
    console.log("no completed job on this stack; left screenshot-results.png alone");
  }
} finally {
  await ctx.close();
  await browser.close();
}
