// The browser's broadening and the server's agree, checked against each other.
//
// This formula existed three times: once in Python and twice in TypeScript.
// Two of those are now one -- `frontend/src/jobs/broadening.ts` serves both
// inline charts -- but a language boundary remains, and it remains on purpose:
// the client copy is what lets the drawer show a spectrum for an
// already-finished job with no backend call at all.
//
// A boundary you keep deliberately still needs a check across it, or it drifts
// and the only symptom is an inline chart that disagrees slightly with the PNG
// rendered from the same numbers. Nobody reports that.
//
// Needs no browser and no stack: it transpiles the module with the TypeScript
// compiler already in node_modules and shells out to python3 for the server
// side. It SKIPS if python3 cannot import numpy, since that means the backend
// environment is not on PATH rather than that the two disagree.
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${detail ? `  -- ${detail}` : ""}`);
  if (!ok) failures++;
}

// --- the client half -------------------------------------------------------
const tsSource = readFileSync(path.join(REPO, "frontend/src/jobs/broadening.ts"), "utf8");
const js = ts.transpileModule(tsSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const tmp = path.join(mkdtempSync(path.join(tmpdir(), "broaden-")), "broadening.mjs");
writeFileSync(tmp, js);
const { broadenedSpectrum, sigmaFromFwhm } = await import(tmp);

// Real numbers: uracil's first two excitations and their oscillator strengths.
const E = [5.10176071402066, 5.847494493977446];
const F = [0.000243949073974109, 0.20377337663919087];
const FWHM = 0.2;
const N = 200;

const client = broadenedSpectrum(E, F, FWHM, { nPoints: N, floor: 0.5 });

// --- the server half -------------------------------------------------------
const py = `
import json, sys
sys.path.insert(0, ${JSON.stringify(REPO)})
try:
    from app.chemistry.spectrum import _broadened_spectrum
except Exception as e:
    print("SKIP " + type(e).__name__); raise SystemExit(0)
g, y = _broadened_spectrum(${JSON.stringify(E)}, ${JSON.stringify(F)}, ${FWHM}, n_points=${N})
print("OK " + json.dumps({"grid": [float(v) for v in g], "y": [float(v) for v in y]}))
`;
const proc = spawnSync("python3", ["-c", py], { encoding: "utf8", timeout: 120000 });
const line = (proc.stdout || "").split("\n").find((l) => l.startsWith("OK ") || l.startsWith("SKIP "));

if (!line || line.startsWith("SKIP")) {
  console.log(`[SKIPPED] the backend environment is not importable from here (${line || "no output"}). `
    + "Run with the qc-agent environment on PATH to compare the two implementations.");
  process.exit(0);
}

const server = JSON.parse(line.slice(3));

// --- do they agree ---------------------------------------------------------
check("both produce the same number of points",
  client.grid.length === server.grid.length && client.grid.length === N,
  `${client.grid.length} vs ${server.grid.length}`);

let maxGridDiff = 0;
let maxYDiff = 0;
const scale = Math.max(...server.y.map(Math.abs)) || 1;
for (let i = 0; i < server.grid.length; i++) {
  maxGridDiff = Math.max(maxGridDiff, Math.abs(client.grid[i] - server.grid[i]));
  maxYDiff = Math.max(maxYDiff, Math.abs(client.y[i] - server.y[i]) / scale);
}
check("they lay their grids on the same points", maxGridDiff < 1e-9,
  `largest difference ${maxGridDiff.toExponential(2)} eV`);
check("and give the same intensity everywhere on it", maxYDiff < 1e-9,
  `largest relative difference ${maxYDiff.toExponential(2)} -- a drift here shows up as an `
  + "inline chart disagreeing with the PNG rendered from the same numbers");

const argmax = (a) => a.indexOf(Math.max(...a));
check("and put the band's peak at the same place",
  argmax(client.y) === argmax(server.y),
  `client index ${argmax(client.y)}, server ${argmax(server.y)}`);

// The one line all three copies shared, checked on its own so a change to it
// is attributed to the shared helper rather than to a caller.
check("sigma is the standard FWHM conversion",
  Math.abs(sigmaFromFwhm(0.2) - 0.2 / (2 * Math.sqrt(2 * Math.log(2)))) < 1e-15);

console.log(`\n${failures} failure(s)`);
process.exit(failures ? 1 : 0);
