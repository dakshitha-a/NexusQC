import { useState } from "react";
import { ChevronDown, ChevronRight, FlaskConical } from "lucide-react";

type Row = { calc: string; pyscf: string | null; orca: string | null; bagel: string | null };

// Mirrors app/chemistry/jobs/registry.py's ALLOWED_ENGINES/DEFAULT_ENGINE --
// kept as a small hand-written table here rather than fetched from the
// backend since it's static per-deployment reference info, not job state.
const ROWS: Row[] = [
  { calc: "Single-point energy (HF / DFT)", pyscf: "default", orca: "yes", bagel: null },
  { calc: "Geometry optimization", pyscf: "default", orca: "yes", bagel: null },
  { calc: "Frequencies / thermochemistry", pyscf: "default", orca: "yes", bagel: "numerical, HF only" },
  { calc: "CASSCF (incl. state-averaged)", pyscf: "default", orca: "yes, + oscillator strengths", bagel: "yes" },
  { calc: "CASPT2", pyscf: null, orca: null, bagel: "default (only option)" },
  { calc: "TDDFT / TDA-DFT / CIS / TD-HF", pyscf: "default", orca: "yes", bagel: null },
  { calc: "EOM-CCSD", pyscf: "energies only", orca: "default, + oscillator strengths", bagel: null },
  { calc: "Orbital (MO) visualization", pyscf: "default", orca: "yes", bagel: "yes" },
  { calc: "Potential-energy scan (multi-image)", pyscf: "default*", orca: "yes*", bagel: "yes*" },
];

function Cell({ value }: { value: string | null }) {
  if (!value) return <td className="py-1.5 pr-3 text-text-muted">—</td>;
  return (
    <td className="py-1.5 pr-3">
      <span className={value.startsWith("default") ? "font-medium text-accent" : "text-text"}>{value}</span>
    </td>
  );
}

export function WelcomeMessage() {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-lg rounded-bl-sm border border-border bg-surface px-4 py-3 text-sm text-text">
        <div className="mb-1.5 flex items-center gap-2 font-medium text-text">
          <FlaskConical size={16} className="text-accent" />
          Computational chemistry assistant
        </div>
        <p className="text-text-muted">
          Name a molecule or paste a SMILES/XYZ and tell me what you want to know -- I'll set up the calculation,
          ask for anything I'm missing, and show you an approval card before anything actually runs.
        </p>

        <div className="mt-2.5 grid gap-1.5 text-text-muted sm:grid-cols-2">
          <div>
            <span className="font-medium text-text">Calculations:</span> single-point energies, geometry
            optimization, frequencies/thermochemistry, CASSCF/CASPT2, TDDFT/CIS/EOM-CCSD excited states, orbital
            (MO) visualization, and interpolated potential-energy scans.
          </div>
          <div>
            <span className="font-medium text-text">Programs:</span> PySCF, ORCA, and BAGEL -- I pick the right
            one automatically based on the method (you can also ask for a specific engine).
          </div>
        </div>

        <button
          onClick={() => setShowDetails((v) => !v)}
          className="mt-2.5 flex items-center gap-1 text-xs text-accent hover:underline"
        >
          {showDetails ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          More details
        </button>

        {showDetails && (
          <div className="mt-2 border-t border-border pt-2.5">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-xs">
                <thead>
                  <tr className="text-left text-text-muted">
                    <th className="py-1 pr-3 font-normal">Calculation</th>
                    <th className="py-1 pr-3 font-normal">PySCF</th>
                    <th className="py-1 pr-3 font-normal">ORCA</th>
                    <th className="py-1 pr-3 font-normal">BAGEL</th>
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map((r) => (
                    <tr key={r.calc} className="border-t border-border">
                      <td className="py-1.5 pr-3">{r.calc}</td>
                      <Cell value={r.pyscf} />
                      <Cell value={r.orca} />
                      <Cell value={r.bagel} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-text-muted">
              <span className="text-accent">Colored</span> = default engine for that calculation.
              * A potential-energy scan runs one calculation per interpolated image, so its engine follows
              whatever calculation type you pick for each image (e.g. a CASSCF scan uses CASSCF's own engine
              choices above). Scans default to IDPP (Image Dependent Pair Potential) interpolation between two
              endpoint geometries -- it aligns the structures and iteratively adjusts each image to avoid atom
              clashes, which behaves better than plain linear Cartesian interpolation or internal-coordinate
              LIIC for anything but a small displacement; true LIIC and linear interpolation are available if you
              ask for them. A single-molecule bond/angle/dihedral scan is also supported.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
