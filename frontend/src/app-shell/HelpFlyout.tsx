import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Flyout } from "./Flyout";
import { useComposerDraftStore } from "../lib/composerDraftStore";

/** A numbered step in the getting-started walkthrough. */
function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-2.5">
      <span className="mt-px flex size-4.5 shrink-0 items-center justify-center rounded-full bg-accent-muted text-[10px] font-medium text-accent">
        {n}
      </span>
      <div className="min-w-0">
        <div className="text-xs font-medium text-text">{title}</div>
        <div className="text-xs leading-relaxed text-text-muted">{children}</div>
      </div>
    </li>
  );
}

/** Collapsible reference section. Local state per section: these are
 *  read-once reference material, not a layout preference worth persisting. */
function Section({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-border py-2.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 text-xs font-semibold uppercase tracking-wide text-text-muted transition-colors hover:text-text"
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {title}
      </button>
      {open && <div className="mt-2 text-xs leading-relaxed text-text">{children}</div>}
    </div>
  );
}

/** One calculation type. `id` is the identifier the agent uses internally --
 *  shown small and secondary, because you never have to type it. */
function JobType({ name, id, children }: { name: string; id: string; children: React.ReactNode }) {
  return (
    <div className="mb-2.5">
      <div className="flex flex-wrap items-baseline gap-x-1.5">
        <span className="text-xs font-medium text-text">{name}</span>
        <span className="font-mono text-[10px] text-text-muted">{id}</span>
      </div>
      <div className="text-xs leading-relaxed text-text-muted">{children}</div>
    </div>
  );
}

export function HelpFlyout({ open, onClose }: { open: boolean; onClose: () => void }) {
  const setDraft = useComposerDraftStore((s) => s.setDraft);

  const tryPrompt = (text: string) => {
    setDraft(text);
    onClose();
  };

  return (
    <Flyout open={open} onClose={onClose} title="How to use NexusQC" widthClassName="w-125">
      {/* --- Getting started ------------------------------------------- */}
      <div className="mb-1">
        <p className="mb-3 text-xs leading-relaxed text-text-muted">
          NexusQC turns a plain-language request into a real quantum chemistry calculation. You stay
          in control of what runs: every job is shown to you as a complete input file first.
        </p>
        <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
          Your first calculation
        </div>
        <ol className="flex flex-col gap-2.5">
          <Step n={1} title="Give it a molecule">
            Type a name (<em>water</em>, <em>benzene</em>), paste a SMILES string or raw XYZ
            coordinates, or draw one with the sketcher — the pen icon in the molecule panel on the
            right. The 3D structure appears there once it resolves.
          </Step>
          <Step n={2} title="Say what you want to know">
            For example{" "}
            <button
              onClick={() => tryPrompt("Optimise the geometry of water with B3LYP/6-31G(d)")}
              className="text-accent hover:underline"
            >
              “optimise the geometry with B3LYP/6-31G(d)”
            </button>
            . If something essential is missing — a basis set, an active space — I'll ask rather than
            pick for you.
          </Step>
          <Step n={3} title="Check the input, then approve">
            An approval card shows the exact input file that will be sent to the program. Nothing
            runs until you click Approve. ORCA and BAGEL inputs can be edited by hand right there;
            PySCF is driven through its Python API, so there is no file to edit.
          </Step>
          <Step n={4} title="Come back to the results">
            Jobs run in the background and survive you closing the tab or logging out. Click any job
            in the right-hand panel for energies, orbitals, spectra, geometries and raw output.
          </Step>
        </ol>
      </div>

      <div className="mt-4">
        {/* --- Reference ----------------------------------------------- */}
        <Section title="What the panels do" defaultOpen>
          <p className="mb-2">
            <span className="font-medium text-text">Left</span> — your conversations, and the
            knowledge base: manuals and papers you upload, which I search for exact syntax and
            background when preparing a calculation.
          </p>
          <p className="mb-2">
            <span className="font-medium text-text">Centre</span> — the chat, and where approval
            cards and plots appear.
          </p>
          <p>
            <span className="font-medium text-text">Right</span> — the active molecule, recent jobs,
            and the job manager covering every conversation. Panels can be collapsed or resized;
            the molecule and orbital views can be expanded full-screen.
          </p>
        </Section>

        <Section title="Calculations you can ask for">
          <JobType name="Single-point energy" id="single_point">
            Energy and dipole at a fixed geometry. Needs a method (HF or DFT) and a basis set.
          </JobType>
          <JobType name="Geometry optimisation" id="geometry_optimization">
            Finds the nearest equilibrium structure, reporting the optimised geometry and the energy
            at each step.
          </JobType>
          <JobType name="Frequencies and thermochemistry" id="frequency">
            Vibrational frequencies, normal modes you can animate, and thermochemical corrections.
            Usually run after an optimisation to confirm you found a true minimum — an imaginary
            frequency means you did not.
          </JobType>
          <JobType name="Excited states from a ground state" id="tddft">
            CIS, TD-HF/RPA, TDA-DFT or full TDDFT — selected automatically from whether the reference
            is HF or DFT and whether the Tamm–Dancoff approximation is used. Gives excitation
            energies and, usually, oscillator strengths for a UV/Vis spectrum.
          </JobType>
          <JobType name="Excited states from coupled cluster" id="eom_ccsd">
            Generally more accurate than TDDFT and considerably more expensive. Oscillator strengths
            require ORCA.
          </JobType>
          <JobType name="Multi-reference (CASSCF)" id="casscf">
            For systems a single determinant describes badly — bond breaking, near-degeneracies, much
            of photochemistry. Needs an active space: how many electrons in how many orbitals.
            State-averaged CASSCF over several states is supported. Oscillator strengths require ORCA.
          </JobType>
          <JobType name="Active-space recommendation" id="recommend_active_space">
            Not sure what active space to use? This analyses the orbitals and suggests one, with
            reasoning. PySCF only.
          </JobType>
          <JobType name="Perturbation theory on top of CASSCF" id="caspt2">
            Adds dynamic correlation to a CASSCF reference for quantitative energies. BAGEL only;
            energies without oscillator strengths.
          </JobType>
          <JobType name="Orbital visualisation" id="mo_visualization">
            Renders orbitals as 3D isosurfaces. Note that you rarely need to ask for this
            specifically — most completed calculations already carry an orbital table you can click
            through.
          </JobType>
          <JobType name="Potential-energy scan" id="pes_scan">
            Steps along a bond, angle or dihedral, or interpolates between two structures, to map a
            reaction or conformational path.
          </JobType>
          <JobType name="Transition-state search" id="neb_ts">
            Nudged elastic band: finds the transition state between two structures you supply as
            endpoints. ORCA only.
          </JobType>
          <JobType name="Custom input file" id="custom">
            Runs an ORCA or BAGEL input you dictate, for calculation types NexusQC has no dedicated
            support for. Same approval gate; results are shown as raw output.
          </JobType>
        </Section>

        <Section title="Working with molecules">
          <p className="mb-2">
            Every structure you name, paste or draw is kept as a numbered frame in the molecule
            panel. Step through them with the slider, and attach any frame to a message to run the
            next calculation on that particular geometry — useful for comparing a starting structure
            with an optimised one.
          </p>
          <p>
            Sketched structures are given sensible 3D coordinates automatically (explicit hydrogens,
            distance-geometry embedding, then a quick force-field clean-up) before being handed to a
            calculation. Atoms are numbered from 1 everywhere, so a number you read off the 3D view
            is the number to use when specifying a bond or angle.
          </p>
        </Section>

        <Section title="Jobs, results and storage">
          <p className="mb-2">
            Calculations run as independent background processes. A CASSCF or CASPT2 job can take
            hours; that is expected, not a problem. Logging out will not stop one, and the results
            will be waiting when you return.
          </p>
          <p>
            Attach one or more finished jobs to a message to ask about them together — comparing
            energies across jobs will produce a chart inline in the conversation.
          </p>
        </Section>

        <Section title="When something goes wrong">
          <p className="mb-2">
            If a job fails, I investigate it without being asked: I read the error, search the
            relevant program manual, and search the web if that is not enough. Then I propose a
            corrected retry, which you approve exactly like any other job. This stops after a few
            attempts rather than looping — at that point I will explain what I think is wrong instead.
          </p>
          <p>
            A calculation that finishes but looks wrong is worth asking about directly. I can read
            the raw output and the orbital table, which is usually where the answer is.
          </p>
        </Section>

        <Section title="Good things to ask">
          <p className="mb-2">
            Beyond running jobs, I can explain a method and its trade-offs, help choose a basis set,
            search uploaded manuals for exact keyword syntax, search published literature, and write
            an input file for a program NexusQC cannot run — which I will hand you as text, saying so
            plainly.
          </p>
          <button
            onClick={() =>
              tryPrompt("What are the trade-offs between TDDFT and EOM-CCSD for excited states?")
            }
            className="text-accent hover:underline"
          >
            Try: “what are the trade-offs between TDDFT and EOM-CCSD?”
          </button>
        </Section>
      </div>
    </Flyout>
  );
}
