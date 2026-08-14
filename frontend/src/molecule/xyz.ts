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
