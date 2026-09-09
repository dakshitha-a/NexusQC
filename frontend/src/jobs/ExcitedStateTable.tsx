import type { ExcitedStateRow } from "./excitedState";
import { STATE_ENERGY_METHODS } from "./excitedState";

const fmt = (v: number | null, digits: number) => (v == null ? ", " : v.toFixed(digits));

export function ExcitedStateTable({ rows, method }: { rows: ExcitedStateRow[]; method: string | null }) {
  // Every CASSCF-based method reports leading CI configurations the same
  // way, so the footnote explaining what a blank cell means applies to all
  // of them, not only to the two the table originally knew about.
  const isMulticonfigurational = method !== null && STATE_ENERGY_METHODS.includes(method);
  return (
    <div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-text-muted">
            <th className="py-1 pr-3 font-normal">State</th>
            <th className="py-1 pr-3 font-normal">Energy (Eh)</th>
            <th className="py-1 pr-3 font-normal">&Delta;E (eV)</th>
            <th className="py-1 pr-3 font-normal">f</th>
            <th className="py-1 font-normal">Dominant transition (weight, c&sup2;)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.stateIndex} className="border-t border-border">
              <td className="py-1 pr-3 font-mono text-text-muted">{r.label}</td>
              <td className="py-1 pr-3 font-mono">{fmt(r.energyHartree, 6)}</td>
              <td className="py-1 pr-3 font-mono">{fmt(r.deltaEv, 3)}</td>
              <td className="py-1 pr-3 font-mono">{fmt(r.f, 4)}</td>
              <td className="py-1 font-mono text-text-muted">{r.dominant ?? ", "}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {isMulticonfigurational && (
        <div className="mt-1.5 text-2xs text-text-muted">
          Dominant transition shows the leading CI configuration(s) as orbital pairs when they resolve to a
          clean single excitation relative to the reference configuration -- ", " means this root IS the
          reference (no dominant excitation character) or its leading configurations are multi-orbital
          excitations that don't reduce to a single orbital pair.
        </div>
      )}
    </div>
  );
}
