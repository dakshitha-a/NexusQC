import { useState } from "react";
import { ChevronDown, ChevronRight, FlaskConical, ArrowUpRight, BookOpen } from "lucide-react";
import { useComposerDraftStore } from "../lib/composerDraftStore";
import { useHelpStore } from "../lib/helpStore";

type Row = { calc: string; pyscf: string | null; orca: string | null; bagel: string | null };

// Mirrors app/chemistry/jobs/registry.py's ALLOWED_ENGINES/DEFAULT_ENGINE --
// kept as a small hand-written table here rather than fetched from the
// backend since it's static per-deployment reference info, not job state.
const ROWS: Row[] = [
  { calc: "Single-point energy (HF / DFT)", pyscf: "default", orca: "yes", bagel: null },
  { calc: "Geometry optimisation", pyscf: "default", orca: "yes", bagel: "CASSCF/CASPT2 only" },
  { calc: "Frequencies / thermochemistry", pyscf: "default", orca: "yes", bagel: "numerical, HF only" },
  { calc: "CASSCF (incl. state-averaged)", pyscf: "default", orca: "yes, + oscillator strengths", bagel: "yes" },
  { calc: "CASPT2", pyscf: null, orca: null, bagel: "default (only option)" },
  { calc: "TDDFT / TDA-DFT / CIS / TD-HF", pyscf: "default", orca: "yes", bagel: null },
  { calc: "EOM-CCSD", pyscf: "energies only", orca: "default, + oscillator strengths", bagel: null },
  { calc: "Orbital (MO) visualisation", pyscf: "default", orca: "yes", bagel: "yes" },
  { calc: "Potential-energy scan", pyscf: "default*", orca: "yes*", bagel: "yes*" },
  { calc: "Transition state (NEB-TS)", pyscf: null, orca: "default (only option)", bagel: null },
  { calc: "Active-space recommendation", pyscf: "default (only option)", orca: null, bagel: null },
  { calc: "Custom input file", pyscf: null, orca: "yes", bagel: "yes" },
];

// Deliberately ordered easiest-first. Each one is a complete, runnable
// request rather than a fragment, so clicking it teaches the phrasing the
// agent understands -- which is most of the learning curve here.
const EXAMPLES: { label: string; prompt: string }[] = [
  {
    label: "See a molecule in 3D",
    prompt: "Show me caffeine",
  },
  {
    label: "Optimise a geometry",
    prompt: "Optimise the geometry of water with B3LYP/6-31G(d)",
  },
  {
    label: "Run a CASSCF",
    prompt:
      "Run a CASSCF(6,6)/cc-pVDZ calculation on formaldehyde and show me the active orbitals",
  },
  {
    label: "Pick an active space",
    prompt:
      "What active space would you recommend for the first excited state of butadiene?",
  },
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
  const setDraft = useComposerDraftStore((s) => s.setDraft);
  const openHelp = useHelpStore((s) => s.openHelp);

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-in px-1">
      {/* Identity */}
      <div className="flex items-center gap-2.5">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-muted">
          <FlaskConical size={18} className="text-accent" />
        </span>
        <div className="min-w-0">
          <h1 className="text-base font-semibold leading-tight text-text">NexusQC</h1>
          <p className="text-xs leading-tight text-text-muted">Agentic Quantum Chemistry Engine</p>
        </div>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-text-muted">
        Describe the calculation you want in plain language. I work out the setup, ask about anything
        genuinely ambiguous rather than guessing, and show you the exact input file before a single
        calculation runs — nothing executes until you approve it.
      </p>

      {/* Example prompts -- prefill the composer rather than sending, so you
          can read and edit before committing. */}
      <div className="mt-4">
        <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Try one
        </div>
        <div className="grid gap-1.5 sm:grid-cols-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              onClick={() => setDraft(ex.prompt)}
              data-testid={`welcome-example-${ex.label.toLowerCase().replace(/\s+/g, "-")}`}
              title={ex.prompt}
              className="group flex items-start gap-2 rounded-md border border-border bg-surface px-3 py-2 text-left transition-colors hover:border-accent hover:bg-surface-raised"
            >
              <ArrowUpRight
                size={13}
                className="mt-0.5 shrink-0 text-text-muted transition-colors group-hover:text-accent"
              />
              <span className="min-w-0">
                <span className="block text-xs font-medium text-text">{ex.label}</span>
                <span className="block truncate text-[11px] text-text-muted">{ex.prompt}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Orientation: three things worth knowing, one line each. */}
      <dl className="mt-4 grid gap-x-5 gap-y-2 text-xs sm:grid-cols-2">
        <div>
          <dt className="font-medium text-text">Building molecules</dt>
          <dd className="text-text-muted">
            Give a name, a SMILES string, or raw XYZ — or draw one with the sketcher (the pen icon in
            the molecule panel). Every structure is kept as a numbered frame you can reuse.
          </dd>
        </div>
        <div>
          <dt className="font-medium text-text">Choosing a program</dt>
          <dd className="text-text-muted">
            PySCF, ORCA and BAGEL are all wired in. I pick whichever one actually supports what you
            asked for, and you can override it by name.
          </dd>
        </div>
        <div>
          <dt className="font-medium text-text">While jobs run</dt>
          <dd className="text-text-muted">
            Calculations run in the background — CASSCF work can take hours. Close the tab and come
            back; results, orbitals and spectra will be waiting.
          </dd>
        </div>
        <div>
          <dt className="font-medium text-text">If something fails</dt>
          <dd className="text-text-muted">
            I read the error, check the program's manual, and propose a corrected retry — which you
            approve like any other job.
          </dd>
        </div>
      </dl>

      {/* Secondary actions */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border pt-2.5">
        <button
          onClick={openHelp}
          data-testid="welcome-open-tutorial"
          className="flex items-center gap-1.5 text-xs text-accent hover:underline"
        >
          <BookOpen size={12} />
          Open the tutorial
        </button>
        <button
          onClick={() => setShowDetails((v) => !v)}
          data-testid="welcome-toggle-details"
          className="flex items-center gap-1 text-xs text-text-muted hover:text-text"
        >
          {showDetails ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          What can it run?
        </button>
      </div>

      {showDetails && (
        <div className="mt-2.5 animate-fade-in">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[440px] text-xs">
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
          <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
            <span className="text-accent">Coloured</span> = the engine chosen by default.
            ORCA and BAGEL are optional and must be licensed and installed separately; without them,
            PySCF still covers most of this table.
            {" "}
            <span className="text-text-muted">
              * A scan runs one calculation per geometry, so it follows the engine rules of whichever
              calculation type you scan.
            </span>
          </p>
        </div>
      )}
    </div>
  );
}
