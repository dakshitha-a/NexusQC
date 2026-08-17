"""Pre-registered expected negatives and the failure-classification
taxonomy, encoded as data so the final report is derived mechanically
rather than written from memory.

Everything in EXPECTED_NEGATIVES is documented design intent. Registering
each one BEFORE the run is what keeps the report from filing intended
behavior as a bug -- and, just as importantly, turns each into a real
assertion: if an expected absence unexpectedly APPEARS, that is itself a
finding, and expect_by_design() fails rather than passing silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check  # noqa: E402

# --------------------------------------------------------------------------
# Failure classification
# --------------------------------------------------------------------------

TAXONOMY = {
    "CODE": "A genuine defect in this repo's code.",
    "ENV": (
        "Environmental, not the app. BAGEL/MKL on this host is documented-flaky "
        "(dsyev/pdsyevd failures, ~80-96s CASSCF macro-iterations for a trivial "
        "system); PubChem/OPSIN/DuckDuckGo/Semantic Scholar are network-dependent. "
        "Reproduce twice and match the documented signature before using this tag."
    ),
    "LLM": (
        "The model did not call the right tool, but the code path is sound. "
        "Disambiguated by the MECHANICAL FALLBACK: re-run the same operation by "
        "calling the mechanism directly via `docker compose exec`. Direct call "
        "works -> LLM. Direct call fails -> CODE."
    ),
    "DOC": "Documentation / README drift.",
    "UX": "Works as coded, but is a usability or polish gap.",
    "DESIGN": "Behaving as intended; matches an EXPECTED_NEGATIVES entry.",
    "HARNESS": "The test itself was wrong. Owned explicitly, never counted as a defect.",
}

# --------------------------------------------------------------------------
# Expected negatives
# --------------------------------------------------------------------------

EXPECTED_NEGATIVES = {
    "XN-01": (
        "No 'Molecular orbitals' section in JobDetailDrawer for "
        "geometry_optimization / frequency / pes_scan -- those job types never "
        "call the molden-export helpers. Deliberate scope boundary."
    ),
    "XN-02": (
        "plot_excited_state_spectrum REFUSES for a PySCF eom_ccsd job. PySCF's "
        "EOMEESinglet has no oscillator-strength support at all, so refusing is "
        "the pass condition -- plotting a flat line would be worse."
    ),
    "XN-03": "plot_excited_state_spectrum REFUSES for a PySCF casscf job (no oscillator strengths).",
    "XN-04": "plot_excited_state_spectrum REFUSES for any caspt2 job (BAGEL-only, energies-only).",
    "XN-05": (
        "BAGEL's orbital_table reports energy_eV = 0.0 for every active-space "
        "orbital. BAGEL has no single-particle Fock eigenvalue for a "
        "multi-configurational active orbital; confirmed in the raw .molden."
    ),
    "XN-06": (
        "No hand-edit textarea on a PySCF approval card -- read-only <pre> instead. "
        "_EDITABLE_ENGINES = {orca, bagel}; PySCF's preview is a synthetic driver "
        "script with nothing an edit could change at execution time."
    ),
    "XN-07": "plot_ir_spectrum REFUSES for a PySCF frequency job (PySCF computes no IR intensities here).",
    "XN-08": (
        "BAGEL geometry_optimization / frequency are structurally confirmed but NOT "
        "convergence-verified. Accept a well-formed result; do not assert a "
        "converged geometry."
    ),
    "XN-09": "neb_ts target_state (excited-state) path is unverified; record observations only.",
    "XN-10": "check_owner_or_admin returns 404, not 403, for another user's resource (enumeration-resistant).",
    "XN-11": "An unowned resource is readable by everyone -- documented ownership policy.",
    "XN-12": "ExpandablePanel overlays are not Radix dialogs, so Escape does nothing on them.",
    "XN-13": "SearchableText swallows the first Escape to clear its find box; a second Escape closes the flyout.",
    "XN-14": (
        "No agent_step SSE events are published after an approval resume. "
        "approve_job -> resume_turn is one blocking .invoke(), and "
        "_publish_new_messages emits only `message` events. The post-approval tool "
        "activity is therefore invisible to AgentStepChips. Expected today; "
        "improvement candidate."
    ),
    "XN-15": (
        "A PySCF job's detail drawer shows neither 'View raw input' nor 'View raw "
        "output' -- both are gated on engine != pyscf, since there is no literal "
        "input file."
    ),
    "XN-16": (
        "Inline auto UV/Vis (drawer section 11) and artifact UV/Vis (section 16) are "
        "mutually exclusive, as are inline IR (15) and artifact IR (17). A check "
        "expecting both will always fail one."
    ),
}


def expect_by_design(xn_id: str, holds: bool, detail: str = "") -> bool:
    """Assert a pre-registered expected negative actually holds.

    `holds` must be True for the DESIGNED behavior. So for XN-02 you pass
    `holds=("refus" in tool_output.lower())` -- the refusal IS the pass.
    A False here means the app did something other than its documented
    intent, which is a real finding."""
    name = f"[{xn_id}] {EXPECTED_NEGATIVES[xn_id][:90]}"
    return check(name, holds, detail)
