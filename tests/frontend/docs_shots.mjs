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
import { BASE_URL, ADMIN_USER, adminPassword, newBrowser, newContext, LOGGED_IN } from "./_helpers.mjs";

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
  // A label a reader of the README would plausibly have typed. The random
  // suffix stays off it: this thread is deleted at the end of the run, and a
  // hex tag in the picture is noise.
  const label = "Water single point, HF/STO-3G";
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

// The results half. The conversation behind the drawer has to have something
// in it: opening a job drawer over the welcome screen shows the results beside
// an invitation to get started, which is not what a reader is being told the
// app does.
try {
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await page.waitForTimeout(1500);

  const rows = await page.locator('[data-testid^="conversation-row-"]').all();
  for (const row of rows.slice(0, 6)) {
    await row.click();
    await page.waitForTimeout(1600);
    const empty = await page.locator('[data-testid="welcome-example-see-a-molecule-in-3d"]').count();
    if (empty === 0) break;
  }

  const job = page.locator('[data-testid^="jobmanager-row-"]').first();
  if (await job.count()) {
    await job.click();
    await page.waitForTimeout(4000);
    await page.screenshot({ path: path.join(DOCS, "screenshot-results.png") });
    console.log("wrote docs/screenshot-results.png");
  } else {
    console.log("no completed job on this stack; left screenshot-results.png alone");
  }
} finally {
  await ctx.close();
  await browser.close();
}
