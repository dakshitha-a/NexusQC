// Normalizes the several incompatible per-engine/method summary shapes for
// excited-state jobs (tddft/eom_ccsd and the CASSCF-based methods) into one row shape the
// UI can render uniformly. This is necessary, not cosmetic: PySCF/BAGEL
// CASSCF report absolute `state_energies_hartree` with no
// `excitation_energies_eV`/`oscillator_strengths` at all, while ORCA CASSCF
// reports both PLUS `excitation_energies_eV`/`oscillator_strengths` of
// length n_states-1 (gaps from state 0, not one entry per state) -- a naive
// `zip(excitation_energies_eV, oscillator_strengths)` table would mislabel
// every ORCA CASSCF row by one and render nothing for PySCF/BAGEL CASSCF.
import type { JobRow } from "../lib/api";

export interface ExcitedStateRow {
  stateIndex: number; // 0 = ground state
  label: string;
  energyHartree: number | null;
  deltaEv: number | null;
  f: number | null;
  dominant: string | null;
}

const HARTREE_TO_EV = 27.211386245988;

function asNumberArray(v: unknown): number[] | undefined {
  return Array.isArray(v) ? (v as number[]) : undefined;
}

// Every method built on a CASSCF wave function writes the same
// state-energies summary shape, so they share one branch below. Keyed on
// `job.method` -- the level of theory, per P2B.4 -- rather than the runner
// key: which summary shape is in front of us is a property of which runner
// wrote it, and each of these methods' name happens to equal its runner key
// (dispatch.py returns `method` unchanged for all of them), so this still
// tells the two shapes apart correctly. It does NOT tell a real
// single_point CASSCF job apart from a cas_reco/autocas one, which also has
// method="casscf" (registry2/tasks.py) but a completely different summary
// shape -- hence the task guard first.
export const STATE_ENERGY_METHODS = ["casscf", "caspt2", "nevpt2", "mcpdft", "lpdft", "cmspdft"];
export function normalizeExcitedStates(
  job: Pick<JobRow, "task" | "subtype" | "method" | "engine" | "summary">,
): ExcitedStateRow[] | null {
  const s = job.summary;
  if (!s) return null;
  if (job.task !== "single_point") return null;

  if (job.method !== null && STATE_ENERGY_METHODS.includes(job.method)) {
    const stateEnergies = asNumberArray(s["state_energies_hartree"]);
    if (!stateEnergies || stateEnergies.length === 0) return null;
    // Every per-excited-state array -- excitation_energies_eV,
    // oscillator_strengths, dominant_transitions -- has length n_states-1
    // and is indexed so entry i describes state i+1. That is now true of
    // every engine rather than only ORCA: the canonical vocabulary
    // (app/chemistry/jobs/facts.py) strips the leading ground-state slot
    // BAGEL used to write as null, so one indexing convention holds
    // everywhere and `[0]` cannot mean two different states.
    const excitationEv = asNumberArray(s["excitation_energies_eV"]);
    const osc = asNumberArray(s["oscillator_strengths"]);
    const dominant = s["dominant_transitions"] as (string | null)[] | undefined;
    const e0 = stateEnergies[0];
    return stateEnergies.map((e, i) => ({
      stateIndex: i,
      label: i === 0 ? "S0 (ground)" : `S${i}`,
      energyHartree: e,
      deltaEv: i === 0 ? 0 : excitationEv?.[i - 1] ?? (e - e0) * HARTREE_TO_EV,
      f: i === 0 ? null : osc?.[i - 1] ?? null,
      // The leading CI configuration(s) for this root, when one is a clean
      // single excitation relative to the block's reference configuration
      // -- null when the root IS the reference itself (no dominant
      // excitation character) or its leading configs are all
      // double+-excitations relative to it. See ExcitedStateTable's
      // footnote: CASSCF roots aren't guaranteed to come out in energy
      // order relative to which one is reference-like, so state 0 isn't
      // guaranteed to be the one showing "no transition".
      dominant: i === 0 ? null : dominant?.[i - 1] ?? null,
    }));
  }

  // Everything else reaching here is subtype "ee" with method in
  // {eom_ccsd, dft, hf} -- dispatch.py routes the non-eom_ccsd cases (full
  // TDDFT/TDA with a DFT reference, or TD-HF/RPA with an HF reference)
  // through the same "tddft" runner, so they share one summary shape here.
  // `job.method` can never equal "tddft": that string is a runner key
  // (dispatch.py's return value), never a stored level of theory.
  //
  // Gating on subtype==="ee" here (rather than trying every job whose
  // summary happens to carry excitation_energies_eV) is safe because there
  // is no path to an excited-state job that leaves subtype anything else:
  // registry2/params.py's `n_states` is `required_when subtype in
  // ["ee","nac","ci"]`, never a signal that sets subtype -- subtype is
  // always decided first, from what the model/user actually asked for.
  if (job.subtype === "ee") {
    const ev = asNumberArray(s["excitation_energies_eV"]);
    if (!ev || ev.length === 0) return null;
    const osc = s["oscillator_strengths"] as (number | null)[] | undefined;
    const dominant = s["dominant_transitions"] as (string | null)[] | undefined;
    // One name, whatever produced it. This used to branch on method to pick
    // between ground_state_ccsd_energy_hartree and
    // ground_state_energy_hartree, which meant a method the branch did not
    // know about silently lost its ground-state row.
    const groundE = typeof s["total_energy_hartree"] === "number"
      ? (s["total_energy_hartree"] as number)
      : null;

    const rows: ExcitedStateRow[] = [];
    if (groundE != null) {
      rows.push({ stateIndex: 0, label: "S0 (ground)", energyHartree: groundE, deltaEv: 0, f: null, dominant: null });
    }
    ev.forEach((e, i) => {
      rows.push({
        stateIndex: i + 1,
        label: `S${i + 1}`,
        energyHartree: groundE != null ? groundE + e / HARTREE_TO_EV : null,
        deltaEv: e,
        f: osc?.[i] ?? null,
        dominant: dominant?.[i] ?? null,
      });
    });
    return rows;
  }

  return null;
}

/** Points suitable for a Gaussian-broadened spectrum -- excited states only
 * (never the ground-state row), and only when at least one oscillator
 * strength is a real, non-zero number. Mirrors the refusal logic in
 * plot_excited_state_spectrum (tools.py): no plot for an all-null/all-zero
 * f array (CASSCF/EOM-CCSD without ORCA, or CASSCF without
 * want_oscillator_strengths) rather than rendering a fabricated flat line. */
export function oscillatorSeries(
  job: Pick<JobRow, "task" | "subtype" | "method" | "engine" | "summary">,
): { energiesEv: number[]; strengths: number[] } | null {
  const rows = normalizeExcitedStates(job);
  if (!rows) return null;
  const pts = rows.filter(
    (r): r is ExcitedStateRow & { deltaEv: number; f: number } => r.stateIndex > 0 && r.deltaEv != null && r.f != null,
  );
  if (pts.length === 0 || pts.every((p) => p.f === 0)) return null;
  return { energiesEv: pts.map((p) => p.deltaEv), strengths: pts.map((p) => p.f) };
}

// Summary keys that ExcitedStateTable/ground-state display already cover --
// excluded from JobDetailDrawer's generic key/value fallback table so
// values aren't rendered twice.
export const EXCITED_STATE_SUMMARY_KEYS = new Set([
  "state_energies_hartree",
  "excitation_energies_eV",
  "excitation_wavelengths_nm",
  "oscillator_strengths",
  "dominant_transitions",
  "total_energy_hartree",
  "n_states_total",
  "n_excited_states",
]);
