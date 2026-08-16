// Shared helpers for tests/frontend/*.spec.mjs -- raw `playwright`
// (chromium.launch), no @playwright/test runner, matching this repo's
// house style of standalone invoke-and-print scripts (see tests/README.md).
import { chromium } from "playwright";

export const BASE_URL = process.env.QC_AGENT_TEST_BASE_URL || "https://127.0.0.1:8443";
export const ADMIN_USER = process.env.QC_AGENT_TEST_ADMIN_USER || "qatest_admin";

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CREDS_FILE = path.join(__dirname, "..", ".admin_creds");

export function adminPassword() {
  if (process.env.QC_AGENT_TEST_ADMIN_PASS) return process.env.QC_AGENT_TEST_ADMIN_PASS;
  if (existsSync(CREDS_FILE)) return readFileSync(CREDS_FILE, "utf8").trim();
  throw new Error("No admin password available -- run tests/backend/_00_bootstrap.py first.");
}

const _results = [];

export function check(name, condition, detail = "") {
  const status = condition ? "PASS" : "FAIL";
  console.log(`[${status}] ${name}${detail ? ` -- ${detail}` : ""}`);
  _results.push([name, condition, detail]);
  return condition;
}

export function summary() {
  const nFail = _results.filter(([, ok]) => !ok).length;
  console.log(`\n${_results.length - nFail}/${_results.length} checks passed in this script.`);
  return nFail === 0;
}

export async function newBrowser() {
  return chromium.launch({ ignoreHTTPSErrors: true });
}

export async function newContext(browser) {
  return browser.newContext({ ignoreHTTPSErrors: true, baseURL: BASE_URL });
}

export async function adminApiLogin(context) {
  const page = await context.newPage();
  const res = await page.request.post(`${BASE_URL}/api/auth/login`, {
    data: { email_or_username: ADMIN_USER, password: adminPassword() },
    headers: { Origin: BASE_URL },
  });
  if (!res.ok()) throw new Error(`admin login failed: ${res.status()} ${await res.text()}`);
  await page.close();
}

export function randSuffix(n = 8) {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  for (let i = 0; i < n; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

export async function mintInvite(context, role = "user") {
  const page = await context.newPage();
  const res = await page.request.post(`${BASE_URL}/api/admin/invites`, {
    data: { role },
    headers: { Origin: BASE_URL },
  });
  const body = await res.json();
  await page.close();
  return body.token;
}

export async function deleteUser(context, userId) {
  const page = await context.newPage();
  await page.request.delete(`${BASE_URL}/api/admin/users/${userId}`, { headers: { Origin: BASE_URL } });
  await page.close();
}

// Registration via the UI doesn't hand back the created user's id (the
// backend response isn't inspected by these black-box specs) -- this
// looks it up by username through the admin API for cleanup purposes.
export async function deleteUserByUsername(adminContext, username) {
  const page = await adminContext.newPage();
  const res = await page.request.get(`${BASE_URL}/api/admin/users`);
  const users = await res.json();
  const found = users.find((u) => u.username === username);
  if (found) {
    await page.request.delete(`${BASE_URL}/api/admin/users/${found.id}`, { headers: { Origin: BASE_URL } });
  }
  await page.close();
  return found?.id ?? null;
}
