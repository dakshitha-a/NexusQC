import { Flyout } from "./Flyout";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">{title}</div>
      <div className="text-xs leading-relaxed text-text">{children}</div>
    </div>
  );
}

function JobType({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div className="font-mono text-xs text-text">{name}</div>
      <div className="text-xs leading-relaxed text-text-muted">{children}</div>
    </div>
  );
}

export function HelpFlyout({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Flyout open={open} onClose={onClose} title="Help" widthClassName="w-125">
      <Section title="Layout">
        <p className="mb-2">
          The left panel holds your conversations, an uploaded knowledge base (manuals and papers the assistant can
          search), and any custom tools it has written and you've approved. The center panel is the chat. The right
          panel shows the active molecule, currently running/recent jobs, and the full cross-conversation job
          manager.
        </p>
      </Section>

      <Section title="Setting a molecule">
        <p>
          Name a molecule ("water", "benzene"), give a SMILES string, or paste raw XYZ/xmol coordinates directly
          into the chat -- the assistant resolves it and shows a 3D structure in the right panel. Use the expand
          icon on that panel for a larger view, and the reset icon to clear it.
        </p>
      </Section>

      <Section title="Running a calculation">
        <p className="mb-2">
          Ask for an input file to be written and shown ("write me an ORCA input for...") without running it, or ask
          to actually run/submit a job. Before anything runs, you'll see an approval card showing the exact input
          that will be sent to the engine -- nothing executes until you approve it. ORCA and BAGEL inputs can be
          hand-edited on that card before approving; PySCF has no literal input file, so its preview is read-only.
        </p>
        <p>
          Jobs run in the background. Click a job in the right panel to see its status, parameters, and results as
          they become available, download its files, or view its geometry/raw output.
        </p>
      </Section>

      <Section title="Job types">
        <JobType name="single_point">Energy (and dipole) at a fixed geometry. Needs a method (HF/DFT) and basis set.</JobType>
        <JobType name="geometry_optimization">
          Finds the nearest equilibrium structure. Same requirements as single_point; reports the optimized geometry
          and energy vs. step.
        </JobType>
        <JobType name="frequency">
          Vibrational frequencies (and normal modes) at a geometry, usually run after an optimization to confirm a
          true minimum.
        </JobType>
        <JobType name="tddft">
          Excited states from a ground-state reference: CIS, TD-HF/RPA, TDA-DFT, or full TDDFT, selected by whether
          the reference is HF or DFT and whether the Tamm-Dancoff approximation is used. Reports excitation energies
          and, usually, oscillator strengths for a UV/Vis spectrum.
        </JobType>
        <JobType name="eom_ccsd">
          Excited states on top of a coupled-cluster (CCSD) reference -- generally more accurate than TDDFT, more
          expensive. Oscillator strengths are only available via ORCA here.
        </JobType>
        <JobType name="casscf">
          Multi-reference excited/ground states for systems a single determinant can't describe well (bond breaking,
          near-degeneracies, some photochemistry). Needs an active space: how many electrons and orbitals to
          correlate. State-averaged CASSCF (multiple states at once) is supported. Oscillator strengths need ORCA.
        </JobType>
        <JobType name="caspt2">
          Adds dynamic correlation on top of a CASSCF reference for more quantitative energies. BAGEL only here;
          energies only, no oscillator strengths.
        </JobType>
        <JobType name="mo_visualization">
          Renders molecular orbitals (HOMO/LUMO or any other orbital by index) as 3D isosurfaces you can inspect in
          the job's detail view.
        </JobType>
        <JobType name="pes_scan">
          Scans energy along a bond/angle/dihedral, or interpolates between two geometries, to map out a reaction or
          conformational path.
        </JobType>
      </Section>

      <Section title="If a job fails">
        <p>
          The assistant automatically investigates a failed job (checking the error, relevant manual excerpts, and
          the web if needed) and proposes a corrected retry, which still needs your approval like any other job.
          This is capped at a few automatic attempts before it stops and asks you directly.
        </p>
      </Section>
    </Flyout>
  );
}
