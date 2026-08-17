// Runner for the tests/e2e/ui specs, mirroring tests/frontend/run_frontend.mjs.
//
// The symlink self-heal is not optional: Node's ESM resolver ignores
// NODE_PATH, so a spec importing "playwright" only resolves if there is a
// node_modules reachable from its own directory. tests/frontend solves it
// the same way.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "..", "..", "..");

for (const dir of [__dirname, path.join(REPO, "tests", "frontend")]) {
  const link = path.join(dir, "node_modules");
  const target = path.join(REPO, "frontend", "node_modules");
  if (!fs.existsSync(link)) {
    try {
      fs.symlinkSync(target, link, "dir");
      console.log(`linked ${link} -> ${target}`);
    } catch (e) {
      console.error(`could not link node_modules for ${dir}: ${e.message}`);
    }
  }
}

const only = process.argv[2];
const specs = fs.readdirSync(__dirname)
  .filter((f) => f.endsWith(".spec.mjs"))
  .filter((f) => !only || f.startsWith(only))
  .sort();

let pass = 0, fail = 0;
const failed = [];
for (const spec of specs) {
  console.log(`\n${"=".repeat(60)}\n=== ${spec}\n${"=".repeat(60)}`);
  const r = spawnSync(process.execPath, [path.join(__dirname, spec)], {
    stdio: "inherit",
    cwd: REPO,
    env: process.env,
  });
  if (r.status === 0) pass++; else { fail++; failed.push(spec); }
}

console.log(`\n${"=".repeat(60)}`);
console.log(`SUMMARY: ${pass} spec(s) passed, ${fail} failed`);
if (failed.length) console.log(`  failed: ${failed.join(", ")}`);
process.exit(fail ? 1 : 0);
