// Acceptance run for the update notice: a REAL update, started from the admin
// console, watched by an ordinary user's browser from announcement to finish.
//
// This updates the deployment it points at. Everyone using it sees the
// banner and the lockout, which is the point. So it is not a .spec.mjs, the
// frontend runner never picks it up, and it refuses to start unless
// QC_AGENT_TEST_ALLOW_UPDATE=1 is set and no real user has a calculation
// running or queued. Run it only when an update is due anyway.
//
//   QC_AGENT_TEST_ALLOW_UPDATE=1 QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8443 \
//     node tests/frontend/accept_update_watch.mjs "note to users"
//
// What it does:
//   1. registers a throwaway test user and opens the app as them (the watcher);
//   2. as the test admin, opens the console's Deployment section, leaves the
//      notice at its default, types the note, types UPDATE and presses Update;
//   3. every 5 s records what the watcher's tab shows: the banner's phase and
//      text, whether the lockout overlay is up, whether the page reloaded, and
//      whether the tab is still signed in; a screenshot on every change;
//   4. stops once the tab shows the done banner, or after 40 minutes.
// It prints a timeline and asserts: scheduled was seen with a countdown,
// imminent was seen, the overlay came up, the tab reloaded, it is signed in
// afterwards without having been shown the sign-in screen, and the done
// banner names the new commit's time. The throwaway user is deleted at the end.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  newBrowser, newContext, adminApiLogin, mintInvite, deleteUserByUsername, openUserMenu, realUsersActive,
  check, summary, BASE_URL, LOGGED_IN, randSuffix,
} from "./_helpers.mjs";

if (process.env.QC_AGENT_TEST_ALLOW_UPDATE !== "1") {
  console.log("[SKIP] accept_update_watch -- this starts a real update; set QC_AGENT_TEST_ALLOW_UPDATE=1");
  process.exit(0);
}
const note = process.argv[2] || "";
const ORIGIN = { headers: { Origin: BASE_URL } };
const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "accept-update-"));
const browser = await newBrowser();
const admin = await newContext(browser);
await adminApiLogin(admin);
const act = await (await admin.request.get(`${BASE_URL}/api/admin/activity`, ORIGIN)).json();
const inFlight = act.users.filter((u) => !(u.username || "").startsWith("qatest_") && (u.running_jobs || u.pending_jobs));
if (inFlight.length) {
  console.log(`[SKIP] accept_update_watch -- real users have calculations in flight: ${inFlight.map((u) => u.username).join(", ")}`);
  await browser.close();
  process.exit(0);
}
const others = await realUsersActive(admin);
if (others) console.log(`note: real users with the app open will see the banner: ${others}`);

const username = "qatest_accept_" + randSuffix(6);
const watcherCtx = await newContext(browser);
const t0 = Date.now();
const stamp = () => `${Math.round((Date.now() - t0) / 1000)}s`;
const timeline = [];
try {
  const token = await mintInvite(admin);
  const reg = await watcherCtx.request.post(`${BASE_URL}/api/auth/register`, {
    ...ORIGIN,
    data: { invite_token: token, email: `${username}@example.test`, username,
            password: "accept-update passphrase long enough", first_name: "QA", last_name: "Watcher" },
  });
  check("the watcher is registered", reg.ok(), `${reg.status()}`);
  const watcher = await watcherCtx.newPage();
  let reloads = 0;
  watcher.on("load", () => { reloads += 1; timeline.push(`${stamp()} watcher tab loaded (#${reloads})`); });
  await watcher.goto(BASE_URL, { waitUntil: "load" });
  await watcher.waitForSelector(LOGGED_IN, { timeout: 20000 });
  const loadsBefore = reloads;

  // Start it from the console, the way an admin would.
  const ap = await admin.newPage();
  await ap.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await ap.waitForSelector(LOGGED_IN, { timeout: 20000 });
  await openUserMenu(ap);
  await ap.locator('[data-testid="admin-open"]').click();
  await ap.locator('[data-testid="admin-nav-deployment"]').click();
  await ap.waitForSelector('[data-testid="deploy-notice-settings"]', { timeout: 20000 });
  if (note) await ap.locator('[data-testid="deploy-notice-message"]').fill(note);
  await ap.locator('[data-testid="deploy-update-phrase"]').fill("UPDATE");
  await ap.locator('[data-testid="deploy-update"]').click();
  timeline.push(`${stamp()} admin pressed Update (notice ${await ap.locator('[data-testid="deploy-notice-minutes"]').inputValue()} min)`);
  await ap.screenshot({ path: path.join(outDir, "admin-after-update.png") });

  const seen = new Set();
  let overlaySeen = false, signinSeen = false, last = "";
  let doneText = "";
  while (Date.now() - t0 < 40 * 60 * 1000) {
    await watcher.waitForTimeout(5000);
    let phase = "", text = "", overlay = false, signedIn = false, signin = false;
    try {
      const b = watcher.locator('[data-testid="update-notice"]');
      if (await b.count()) { phase = (await b.getAttribute("data-phase")) || ""; text = (await b.innerText()).replace(/\s+/g, " "); }
      overlay = (await watcher.locator("text=NexusQC is being updated").count()) > 0;
      signedIn = (await watcher.locator(LOGGED_IN).count()) > 0;
      signin = (await watcher.locator('input[placeholder="Password"]').count()) > 0;
    } catch { /* mid-reload */ continue; }
    if (overlay) overlaySeen = true;
    if (signin) signinSeen = true;
    const key = `${phase}|${overlay}|${signedIn}|${signin}`;
    if (key !== last) {
      last = key;
      if (phase) seen.add(phase);
      timeline.push(`${stamp()} phase=${phase || "-"} overlay=${overlay} signedIn=${signedIn} signinScreen=${signin} :: ${text.slice(0, 140)}`);
      await watcher.screenshot({ path: path.join(outDir, `${String(timeline.length).padStart(2, "0")}-${phase || (overlay ? "overlay" : "none")}.png`) });
    }
    if (phase === "done" && signedIn) { doneText = text; break; }
    if (phase === "failed" || phase === "cancelled") break;
  }
  console.log("\ntimeline:\n  " + timeline.join("\n  "));
  check("the watcher saw the scheduled notice", seen.has("scheduled"));
  check("and the one-minute warning", seen.has("imminent"));
  check("the lockout overlay came up", overlaySeen);
  check("the tab reloaded itself", reloads > loadsBefore, `${reloads - loadsBefore} load(s)`);
  check("and was never shown the sign-in screen", !signinSeen);
  check("it ends signed in, with the done banner", doneText.includes("was updated at"), doneText);
} finally {
  await deleteUserByUsername(admin, username).catch(() => {});
  await browser.close();
  console.log(`\nscreenshots: ${outDir}`);
}
summary();
