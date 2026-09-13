import { useState } from "react";
import { ChevronDown, ChevronRight, ArrowUpRight, BookOpen } from "lucide-react";
import { LogoLockup } from "../brand/Logo";
import { useComposerDraftStore } from "../lib/composerDraftStore";
import { useHelpStore } from "../lib/helpStore";

type Row = { calc: string; pyscf: string | null; orca: string | null; bagel: string | null };

// GENERATED from app/chemistry/registry2 by
// scripts/generate_capability_docs.py -- do not edit capabilityRows.json by
// hand, and run that script (or its --check mode, which
// scripts/check_capability_matrix.py already calls) after changing a
// capability row.
//
// It was a hand-written table, with a comment saying it mirrored
// app/chemistry/jobs/registry.py -- a module the registry-v2 rewrite
// deleted. Four of its twelve rows had drifted from what the app actually
// runs (R-061), and this is the first thing a new user reads, so it is the
// worst place in the app to be wrong about what it can do. Still a build
// artifact rather than a fetch: the welcome screen has to render before
// anything else works, and a committed JSON keeps the drift visible in a
// diff.
import generatedRows from "./capabilityRows.json";

const ROWS: Row[] = generatedRows as Row[];


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
  if (!value)
    return (
      <td className="py-1.5 pr-3 text-text-muted">
        <span aria-label="not supported" title="Not supported by this engine">
          &ndash;
        </span>
      </td>
    );
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
      {/* Identity. Was a generic lucide flask on a tinted square, which is
          what the app used in place of a logo it did not have. */}
      <LogoLockup size={40} subtitle />

      <p className="mt-3 text-sm leading-relaxed text-text-muted">
        Describe the calculation you want in plain language. I work out the setup, ask about anything
        genuinely ambiguous rather than guessing, and show you the exact input file before a single
        calculation runs, nothing executes until you approve it.
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
                <span className="block truncate text-2xs text-text-muted">{ex.prompt}</span>
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
            Give a name, a SMILES string, or raw XYZ, or draw one with the sketcher (the pen icon in
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
            Calculations run in the background. CASSCF work can take hours. Close the tab and come
            back; results, orbitals and spectra will be waiting.
          </dd>
        </div>
        <div>
          <dt className="font-medium text-text">If something fails</dt>
          <dd className="text-text-muted">
            I tell you plainly and change nothing. Press Troubleshoot and I read the engine's
            output and the program's manual, explain what went wrong, and suggest a fix you
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
          <p className="mt-2 text-2xs leading-relaxed text-text-muted">
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
