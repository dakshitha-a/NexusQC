#!/usr/bin/env node
// Runs every tests/frontend/*.spec.mjs script in sequence against a LIVE
// stack (https://127.0.0.1:8443 by default -- see tests/README.md),
// aggregating PASS/FAIL and exiting non-zero if any script fails.
import { existsSync, readdirSync, symlinkSync, unlinkSync } from "node:fs";
import os from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { spawnSync } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Node's ESM resolver walks up from the IMPORTING FILE's own path looking
// for node_modules -- it ignores NODE_PATH entirely (that's CJS-`require`-
// only), so tests/frontend/_helpers.mjs's `import "playwright"` can't see
// frontend/node_modules on its own. A symlink at tests/frontend/node_modules
// is the standard fix; self-heal it here rather than requiring a manual
// one-time step before `npm run test:e2e` works.
const nodeModulesLink = path.join(__dirname, "node_modules");
if (!existsSync(nodeModulesLink)) {
  symlinkSync(path.join(__dirname, "..", "..", "frontend", "node_modules"), nodeModulesLink);
}

const specs = readdirSync(__dirname)
  .filter((f) => f.endsWith(".spec.mjs"))
  .sort();

// Every run proves it left real users' data alone; see tests/integrity.py.
// The stack is also a research group's deployment.
const repoRoot = path.join(__dirname, "..", "..");
const snapshotPath = path.join(os.tmpdir(), `nexusqc-integrity-${process.pid}.json`);
const snap = spawnSync("python3", ["tests/integrity.py", "snapshot", snapshotPath], { cwd: repoRoot, stdio: "inherit" });
if (snap.status !== 0) {
  console.log("could not take the integrity snapshot; refusing to run");
  process.exit(1);
}

let nFailed = 0;
const failedNames = [];

for (const spec of specs) {
  console.log("\n" + "=".repeat(70));
  console.log(`  ${spec}`);
  console.log("=".repeat(70));
  const result = spawnSync(process.execPath, [path.join(__dirname, spec)], { stdio: "inherit" });
  if (result.status !== 0) {
    nFailed++;
    failedNames.push(spec);
  }
}

console.log("\n" + "=".repeat(70));
console.log(`  SUMMARY: ${specs.length - nFailed}/${specs.length} specs reported all checks passing`);
console.log("=".repeat(70));
const integrity = spawnSync("python3", ["tests/integrity.py", "compare", snapshotPath], { cwd: repoRoot, stdio: "inherit" });
try { unlinkSync(snapshotPath); } catch { /* already gone */ }
if (integrity.status !== 0) {
  console.log("The run above lost data belonging to real users. Restore it from the");
  console.log("backup directory before anything else; see docs/DEPLOYMENT.md.");
  process.exit(1);
}
if (nFailed > 0) {
  console.log("Specs with at least one FAIL (expected for fe_sec_* specs that PASS");
  console.log("when they confirm a real gap -- see tests/README.md):");
  for (const name of failedNames) console.log(`  - ${name}`);
  process.exit(1);
}
process.exit(0);
