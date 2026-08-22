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
            coordinates, or draw one with the sketcher, the pen icon in the molecule panel on the
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
            . If something essential is missing, a basis set, an active space. I'll ask rather than
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
            <span className="font-medium text-text">Left</span>. Your conversations, the
            knowledge base (manuals and papers you upload, which I search for exact syntax and
            background when preparing a calculation), and Files: geometry (.xyz) and engine-input
            (.inp/.input/.json) uploads, attachable to the conversation from there or straight from
            the composer's + button.
          </p>
          <p className="mb-2">
            <span className="font-medium text-text">Centre</span>, the chat, and where approval
            cards and plots appear.
          </p>
          <p>
            <span className="font-medium text-text">Right</span>. The active molecule, recent jobs,
            and the job manager covering every conversation. Panels can be collapsed or resized;
            the molecule and orbital views can be expanded full-screen.
          </p>
        </Section>

        <Section title="Calculations you can ask for">
          <p className="mb-2 text-text-muted">
            The identifier next to each is the kind of calculation (the <em>task</em>); the level of
            theory (HF, DFT, MP2, CCSD, CASSCF, CASPT2, EOM-CCSD…) is a separate choice on top of it,
            so the same task can run at whichever level fits.
          </p>
          <JobType name="Single-point energy" id="single_point/gs">
            Energy and dipole at a fixed geometry. Needs a method (HF or DFT, or a correlated method
            like MP2/CCSD/CASSCF/CASPT2) and a basis set.
          </JobType>
          <JobType name="Excited-state energies" id="single_point/ee">
            CIS/TD-HF/TDA-DFT/full TDDFT from an HF or DFT reference, EOM-CCSD, or state-averaged
            CASSCF/CASPT2 for systems a single determinant describes badly. Bond breaking,
            near-degeneracies, much of photochemistry (needs an active space: electrons and orbitals).
            Gives excitation energies and, usually, oscillator strengths for a UV/Vis spectrum.
          </JobType>
          <JobType name="Energy gradient" id="single_point/grad">
            The forces on every atom at the current geometry, ground- or excited-state.
          </JobType>
          <JobType name="Non-adiabatic coupling" id="single_point/nac">
            The coupling vector between two electronic states, where a Born–Oppenheimer surface
            hopping treatment would need it.
          </JobType>
          <JobType name="Geometry optimisation" id="opt/min">
            Finds the nearest equilibrium structure, reporting the optimised geometry and the energy
            at each step. A constrained optimisation (a bond/angle/dihedral held fixed) or a
            conical-intersection optimisation are the same task with a different subtype.
          </JobType>
          <JobType name="Frequencies and thermochemistry" id="freq">
            Vibrational frequencies, normal modes you can animate, and thermochemical corrections.
            Usually run after an optimisation to confirm you found a true minimum. An imaginary
            frequency means you did not; asking for both together in one job is
            <span className="font-mono text-[11px]"> opt_freq</span>.
          </JobType>
          <JobType name="Active-space recommendation" id="cas_reco">
            Not sure what active space to use for a CASSCF/CASPT2 job? This analyses the orbitals
            (entanglement-based, or AVAS) and suggests one, with reasoning, or explains a space you
            already chose. PySCF only.
          </JobType>
          <JobType name="Potential-energy scan" id="pes_1d / interp_pes">
            Steps along a bond, angle or dihedral, or interpolates between two structures, to map a
            reaction or conformational path.
          </JobType>
          <JobType name="Transition-state search" id="neb_ts">
            Nudged elastic band: finds the transition state between two structures you supply as
            endpoints. ORCA only.
          </JobType>
          <JobType name="Nuclear-ensemble (Wigner) spectrum" id="wigner_spectra">
            Samples geometries from a completed frequency job's normal modes and pools every sample's
            absorption spectrum into one broadened curve with a per-excited-state breakdown.
          </JobType>
          <JobType name="Batch" id="batch">
            Runs a single-point, optimisation, frequency, or optimisation+frequency job over every
            geometry in a geometry set, a scan, or 3+ structures tagged in the molecule panel, one
            independent job per geometry.
          </JobType>
          <JobType name="Blind engine input" id="blind">
            Runs an ORCA or BAGEL input you dictate or attach verbatim, for anything NexusQC has no
            dedicated support for, same approval gate, results shown as raw output. PySCF is never
            run this way: a pasted Python script is recognised but never executed.
          </JobType>
        </Section>

        <Section title="Working with molecules">
          <p className="mb-2">
            Every structure you name, paste or draw is kept as a numbered frame in the molecule
            panel. Step through them with the slider, and attach any frame to a message to run the
            next calculation on that particular geometry. Useful for comparing a starting structure
            with an optimised one.
          </p>
          <p className="mb-2">
            Sketched structures are given sensible 3D coordinates automatically (explicit hydrogens,
            distance-geometry embedding, then a quick force-field clean-up) before being handed to a
            calculation. Atoms are numbered from 1 everywhere, so a number you read off the 3D view
            is the number to use when specifying a bond or angle.
          </p>
          <p>
            Uploading a geometry file works the same way as naming or sketching one, it just skips
            straight to already having coordinates. One geometry in the file becomes the active
            molecule; two become both ends of a path (for later interpolation or an NEB search);
            three or more become a <span className="font-mono text-[11px]">geometry_set</span> job
            instead. Nothing runs, it just holds every geometry so you can step through them and
            pull any single one into a calculation later.
          </p>
        </Section>

        <Section title="Jobs, results and storage">
          <p className="mb-2">
            Calculations run as independent background processes. A CASSCF or CASPT2 job can take
            hours; that is expected, not a problem. Logging out will not stop one, and the results
            will be waiting when you return.
          </p>
          <p>
            Attach one or more finished jobs to a message to ask about them together. Comparing
            energies across jobs will produce a chart inline in the conversation.
          </p>
        </Section>

        <Section title="When something goes wrong">
          <p className="mb-2">
            If a job fails, I say so and stop. Nothing is changed and nothing is resubmitted.
            The failure notice carries a <strong>Troubleshoot</strong> button; press it and I read
            the engine's actual output, search the relevant program manual, and search the web if
            that is not enough, then explain what went wrong. If I can suggest a corrected job you
            approve it exactly like any other. I never rerun a calculation on my own initiative,
            because a guess at a fix can cost hours of compute you did not agree to.
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
            an input file for a program NexusQC cannot run, which I will hand you as text, saying so
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
