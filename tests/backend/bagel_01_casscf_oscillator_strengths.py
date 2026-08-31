"""BAGEL asks for CASSCF oscillator strengths, and reads the answer.

The capability table has recorded `osc_strengths=True` for bagel+casscf since
it was written, and `supports()` offered BAGEL for a CASSCF `wigner_spectra`
ensemble on the strength of it. What was missing sat one layer down:
`bagel_runner._build_input` emitted the forces+dipole block only for CASPT2,
so a CASSCF job carrying `want_oscillator_strengths: True` had the flag
silently dropped, computed no intensities, and said nothing about it.

Job `bc26178c7406` in this repository's data directory is what that cost:
a 50-sample uracil ensemble, `want_oscillator_strengths: True` in its spec,
`oscillator_strengths: None` in every child, and a pooled spectrum with
nothing to convolve.

Checks here are ordered cheapest first. The input-shape and parser checks need
nothing installed; the live check needs BAGEL and is SKIPPED, not failed, when
it is absent -- a missing engine is not a regression. The live one is the
check that matters, because this engine's own `fix_atom` row is the standing
example in docs/PARSER_GAPS.md of why "it ran without error" proves nothing.

Run:  PYTHONPATH=$PWD python3 tests/backend/bagel_01_casscf_oscillator_strengths.py
"""
import json
import os
import shutil
import sys
import tempfile

from app.chemistry.jobs import bagel_runner
from app.chemistry.jobs.dispatch import resolve_runner
from app.chemistry.registry2.params import PARAMS_BY_NAME
from app.chemistry.registry2.routing import route_engine
from app.chemistry.registry2.tasks import supports

failures = []
skips = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


def skip(name, why):
    print("[SKIP] %s  -- %s" % (name, why))
    skips.append(name)


MOLECULE = {
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.469], [0.0, -0.757, -0.469]],
    "charge": 0,
    "multiplicity": 1,
}
BASE_PARAMS = {"basis": "cc-pvdz", "active_electrons": 4, "active_orbitals": 4, "n_states": 3}


def blocks_for(**extra):
    params = {**BASE_PARAMS, **extra}
    bagel_input, _ = bagel_runner._build_input(MOLECULE, params, "casscf")
    return bagel_input["bagel"]


def forces_of(blocks):
    return next((b for b in blocks if b.get("title") == "forces"), None)


# --- the input carries the request ----------------------------------------
asked = forces_of(blocks_for(want_oscillator_strengths=True))
check("a CASSCF job wanting intensities emits a forces block", asked is not None,
      "this block is the only way BAGEL prints transition dipoles at all")
if asked:
    check("the forces block sets dipole", asked.get("dipole") is True)
    check("the forces block asks for NO gradients", asked.get("grads") == [],
          "an empty grads list is what makes this cheap; the CASPT2 path deliberately "
          "asks for one per state and is verified in that shape")
    nested = (asked.get("method") or [{}])[0]
    check("the nested method restates this job's own CASSCF",
          nested.get("title") == "casscf" and nested.get("nstate") == 3
          and nested.get("nact") == 4 and "nspin" in nested,
          "nspin is what confines the state average to one multiplicity")

check("a CASSCF job not asking for intensities emits no forces block",
      forces_of(blocks_for()) is None,
      "the block costs real time; it is not free to add unconditionally")
check("a single-state job emits no forces block",
      forces_of(blocks_for(want_oscillator_strengths=True, n_states=1)) is None,
      "there is no transition to have an intensity")


# --- the parser reads the answer, and does not confuse the two methods -----
SAMPLE = """
  * CASSCF dipole moments

    * State             0 :   (    0.223909,     1.503562,     0.000000) a.u.

    * Transition    1 - 0 :   (    0.000000,    -0.000000,     0.070797) a.u.
    * Oscillator strength :   0.000646 a.u.

    * Transition    2 - 0 :   (    1.466421,     0.415997,    -0.000000) a.u.
    * Oscillator strength :   0.389710 a.u.

    * Transition    2 - 1 :   (    0.000000,     0.000000,    -0.009004) a.u.
    * Oscillator strength :   0.000003 a.u.

  * CASPT2 dipole moments

    * Transition    1 - 0 :   (    0.000000,    -0.000000,     0.111111) a.u.
    * Oscillator strength :   0.111111 a.u.

    * Transition    2 - 0 :   (    1.000000,     0.000000,    -0.000000) a.u.
    * Oscillator strength :   0.222222 a.u.
"""

casscf_osc = bagel_runner._parse_bagel_oscillator_strengths(SAMPLE, 3, "CASSCF")
check("CASSCF strengths are read, ground-state-relative only",
      casscf_osc == [0.000646, 0.389710],
      "the 'Transition 2 - 1' line is a real transition and deliberately not reported, "
      "matching excitation_energies_eV's convention on every engine here")
check("a CASPT2 section in the same output is not read as CASSCF",
      bagel_runner._parse_bagel_oscillator_strengths(SAMPLE, 3, "CASPT2") == [0.111111, 0.222222],
      "these are different numbers for the same transitions; mixing them has no symptom")
check("a missing section is None, not an empty list",
      bagel_runner._parse_bagel_oscillator_strengths("nothing here", 3, "CASSCF") is None,
      "None is what makes run_casscf attach its explanatory note")


# --- the cascade ----------------------------------------------------------
check("BAGEL is offered for a CASSCF nuclear-ensemble spectrum",
      supports("bagel", "casscf", "wigner_spectra", "").supported)
check("an ensemble's child job routes to the runner that now asks",
      resolve_runner("single_point", "ee", "casscf") == ("casscf", None),
      "the fix is in run_casscf; a child landing anywhere else would not get it")
check("PySCF is still refused -- it genuinely has no route",
      not supports("pyscf", "casscf", "wigner_spectra", "").supported)

decision = route_engine("casscf", "single_point", "ee", None, {"want_oscillator_strengths": True})
check("with no engine named, CASSCF + intensities goes to BAGEL",
      decision.engine == "bagel",
      "the deployment's preference, set 2026-08-31; it went to ORCA before")
check("the reason says preferred, not only",
      "only engine" not in decision.reason.lower() and "preferred" in decision.reason.lower(),
      decision.reason)
check("ORCA is still used when asked for by name",
      route_engine("casscf", "single_point", "ee", "orca",
                   {"want_oscillator_strengths": True}).engine == "orca",
      "a preference decides the default; it does not remove the alternative")
check("a CASSCF job NOT wanting intensities is unaffected",
      route_engine("casscf", "single_point", "ee", None, {}).engine == "pyscf",
      "the rule is about intensities, not about CASSCF")
check("an ensemble, which always wants intensities, follows the same preference",
      route_engine("casscf", "wigner_spectra", "", None,
                   {"want_oscillator_strengths": True}).engine == "bagel")


# --- what the MODEL reads, which is not the same text --------------------
# The routing decision above is computed. This is prose, and prose is what
# the agent actually answers from: `lookup_capabilities` surfaces the
# ParamSpec help, and after the runner, the routing rule, the capability
# notes, the README and PARSER_GAPS were all corrected, this string still
# said ORCA was "the only engine here that computes them" -- so the agent
# went on telling users BAGEL could not do it. A claim that is wrong here is
# wrong in the only place the user ever sees it.
osc_help = PARAMS_BY_NAME["want_oscillator_strengths"].help
check("the parameter help does not claim one engine is the only one",
      "only engine" not in osc_help, osc_help)
check("the parameter help names BAGEL as able to do this",
      "BAGEL" in osc_help,
      "the agent answers 'can BAGEL do this?' out of this sentence")
check("and still says PySCF cannot",
      "PySCF" in osc_help,
      "the real constraint, and the reason the engine set is narrowed at all")


# --- live: the generated input really produces the section ----------------
if not shutil.which(str(bagel_runner.BAGEL_BIN or "")) and not os.path.exists(str(bagel_runner.BAGEL_BIN or "")):
    skip("a real BAGEL run reports oscillator strengths", "BAGEL is not installed here")
else:
    job_dir = tempfile.mkdtemp(prefix="bagel_osc_")
    try:
        out = bagel_runner.run_casscf(
            MOLECULE, {**BASE_PARAMS, "want_oscillator_strengths": True, "_job_dir": job_dir})
        summary = out["summary"]
        osc = summary.get("oscillator_strengths")
        check("a real BAGEL run reports oscillator strengths",
              isinstance(osc, list) and len(osc) == 2 and all(v is not None for v in osc),
              "water/cc-pVDZ CAS(4,4), 3 states: %s" % json.dumps(osc))
        check("a successful run carries no unavailable-note",
              summary.get("oscillator_strengths_note") is None,
              summary.get("oscillator_strengths_note") or "")
        check("the intensities line up with the excitation energies",
              len(summary.get("excitation_energies_eV") or []) == len(osc or []),
              "both are ground-state-relative and index 0 is S1")
    except Exception as e:
        check("a real BAGEL run reports oscillator strengths", False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)

print("\n%d failure(s), %d skipped" % (len(failures), len(skips)))
sys.exit(1 if failures else 0)
