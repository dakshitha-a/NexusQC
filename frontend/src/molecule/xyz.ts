import type { MoleculeDict } from "../lib/api";

export function moleculeToXyzBlock(molecule: MoleculeDict): string {
  return [
    String(molecule.symbols.length),
    molecule.name ?? "molecule",
    ...molecule.symbols.map((el, i) => {
      const [x, y, z] = molecule.coords[i];
      return `${el} ${x.toFixed(8)} ${y.toFixed(8)} ${z.toFixed(8)}`;
    }),
  ].join("\n");
}

/** Inverse of the multi-frame writer in app/chemistry/jobs/base.py's
 * _write_path_xyz -- one MoleculeDict per frame, in path order. Every
 * frame's atom-count line is its own delimiter (standard xmol
 * multi-frame convention, no blank-line separator), so this just walks
 * the text repeatedly consuming "count / comment / count-many atom
 * lines" blocks. charge/multiplicity aren't carried in the xyz text
 * itself, so every frame defaults to 0/1 -- fine here since the scan
 * viewer only ever uses this for geometry display, never for submitting
 * a job (the underlying per-image jobs already ran with their own
 * correct molecule dicts). */
export function parseMultiFrameXyz(text: string): MoleculeDict[] {
  const lines = text.split("\n");
  const frames: MoleculeDict[] = [];
  let i = 0;
  while (i < lines.length) {
    const countLine = lines[i]?.trim();
    if (!countLine) {
      i++;
      continue;
    }
    const n = parseInt(countLine, 10);
    if (!Number.isFinite(n) || n <= 0) break;
    const name = lines[i + 1]?.trim() || `frame ${frames.length}`;
    const symbols: string[] = [];
    const coords: [number, number, number][] = [];
    for (let k = 0; k < n; k++) {
      const parts = lines[i + 2 + k]?.trim().split(/\s+/) ?? [];
      symbols.push(parts[0]);
      coords.push([Number(parts[1]), Number(parts[2]), Number(parts[3])]);
    }
    frames.push({ name, symbols, coords, charge: 0, multiplicity: 1 });
    i += 2 + n;
  }
  return frames;
}

/**
 * Hill notation: carbon first, then hydrogen, then everything else
 * alphabetically. Mirrors `_molecular_formula` in app/chemistry/molecule.py so
 * a formula shown here reads identically to one the backend generated.
 *
 * Used as the molecule panel's title when a frame has no name. The previous
 * fallback was the SMILES, which for anything past a few atoms is both
 * unreadable as a title and long enough to wrap -- the specific cause of the
 * panel resizing as you scrubbed from water to uracil.
 */
export function molecularFormula(symbols: string[]): string {
  const counts = new Map<string, number>();
  for (const s of symbols) counts.set(s, (counts.get(s) ?? 0) + 1);
  const rest = [...counts.keys()].filter((s) => s !== "C" && s !== "H").sort();
  const order = (["C", "H"] as string[]).filter((s) => counts.has(s)).concat(rest);
  return order.map((s) => `${s}${counts.get(s)! > 1 ? counts.get(s) : ""}`).join("");
}
