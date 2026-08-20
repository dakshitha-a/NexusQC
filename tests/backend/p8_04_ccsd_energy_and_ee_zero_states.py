#!/usr/bin/env python3
"""Phase 8 P8.4 -- a user-reported bug, found in a real conversation: asking
for "eom-ccsd with only the ground state" (n_states=0) crashed on both
PySCF (IndexError deep in the Davidson solver) and ORCA (exit code 55,
"Number of roots is not set"), and the natural fallback -- "just run plain
CCSD instead" -- ALSO failed, because a plain single_point/gs energy at
method='ccsd'/'mp2' was never actually wired up in either runner despite
registry2/capabilities.py already claiming energy=True for both, with real
citations. Two bugs, found from the two real job directories the failing
conversation left behind (data/jobs/838df02c5d93, data/jobs/a1b38c902757):

  n_states=0 -> nroots=0 -> pyscf.cc.eom_rccsd's Davidson solver crashes;
  ORCA's MDCI module refuses outright with its own "NRoots>0!" error.

This script pins both fixes:

1. registry2/elicitation.py's validate_draft() now recognizes n_states=0 on
   a single_point/ee draft, for a single-reference method, as "the user
   wants the ground state only" and silently reroutes to a plain
   single_point/gs draft (method='ccsd' in place of 'eom_ccsd'; hf/dft need
   no method translation) rather than letting a meaningless nroots=0 reach
   either engine. Multireference (casscf/caspt2) is deliberately excluded:
   there n_states already INCLUDES the ground state, so n_states=1 (not 0)
   is that method's own "ground state only", through the ordinary
   state-average machinery -- not this bug.

2. app/chemistry/jobs/pyscf_runner.py's run_single_point and
   app/chemistry/jobs/orca_runner.py's run_single_point/build_input_text
   now actually build a plain CCSD/MP2 ground-state energy (PySCF: the same
   cc.CCSD(mf)/mp.MP2(mf) construction run_gradient already used, minus the
   now-unneeded nuc_grad_method() call; ORCA: the bare '! CCSD'/'! MP2'
   bang keyword, no %mdci block -- a ground-state-only CCSD/MP2 energy
   needs no NRoots at all), closing the gap between what capabilities.py
   already promised and what the dispatcher could actually build.

Every engine-facing check here is a REAL run (real PySCF cc.CCSD/mp.MP2,
real ORCA 6.1.1 binary via QC_AGENT_ORCA_BIN) -- not a parser fixture --
because this exact bug was two runner ValueErrors that no amount of
registry-table inspection would have caught; only actually building and
running the job did, both times.

Run:  PYTHONPATH=$PWD python3 tests/backend/p8_04_ccsd_energy_and_ee_zero_states.py
"""
from __future__ import annotations

import sys
import tempfile

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}


def _pyscf_energy_checks(job_dir: str) -> dict[str, float]:
    print("\n== PySCF: plain single_point/gs energy at method='ccsd'/'mp2' now runs ==")
    from app.chemistry.jobs.pyscf_runner import build_input_preview, run_single_point

    energies: dict[str, float] = {}
    for method in ("ccsd", "mp2"):
        result = run_single_point(WATER, {"method": method, "basis": "sto-3g", "_job_dir": job_dir})
        summary = result["summary"]
        energies[method] = summary["energy_hartree"]
        check(f"pyscf single_point/gs method='{method}' converges and reports an energy",
              summary["converged"] and isinstance(summary["energy_hartree"], float),
              summary)
        check(f"pyscf {method} energy is below its own HF reference (real correlation recovered)",
              summary["energy_hartree"] < summary["reference_energy_hartree"],
              (summary["energy_hartree"], summary["reference_energy_hartree"]))

    preview = build_input_preview("single_point", WATER, {"method": "ccsd", "basis": "sto-3g"})
    check("the approval-card preview for method='ccsd' shows the real cc.CCSD construction, "
          "not the old hf/dft-only _mf_lines path",
          "cc.CCSD(mf)" in preview and "Unsupported method" not in preview,
          preview)
    return energies


def _orca_energy_checks(job_dir: str, pyscf_energies: dict[str, float]) -> None:
    print("\n== ORCA: plain single_point/gs energy at method='ccsd'/'mp2' now runs (real ORCA 6.1.1) ==")
    from app.chemistry.jobs.orca_runner import build_input_text, run_single_point

    text = build_input_text("single_point", WATER, {"method": "ccsd", "basis": "sto-3g"})
    check("the built input is a bare '! CCSD' bang line, no %mdci NRoots block "
          "(a ground-state-only CCSD energy needs no roots at all)",
          "! CCSD" in text.upper().split("\n")[0] and "%mdci" not in text.lower(),
          text)

    for method in ("ccsd", "mp2"):
        result = run_single_point(WATER, {"method": method, "basis": "sto-3g", "_job_dir": job_dir})
        orca_energy = result["summary"].get("energy_hartree")
        check(f"orca single_point/gs method='{method}' reports a real energy from a real ORCA run",
              isinstance(orca_energy, float) and orca_energy < -74.9,
              orca_energy)
        check(f"ORCA and PySCF agree on the {method.upper()}/STO-3G water energy to 3 decimal "
              f"places (same physical quantity, two independent implementations computing it)",
              abs(orca_energy - pyscf_energies[method]) < 1e-3,
              (orca_energy, pyscf_energies[method]))


def _elicitation_checks() -> None:
    print("\n== validate_draft: n_states=0 on single_point/ee reroutes instead of crashing ==")
    from app.chemistry.registry2.elicitation import validate_draft

    state = {"molecule": WATER}

    # The EXACT shape of the two real failed jobs (data/jobs/838df02c5d93,
    # data/jobs/a1b38c902757): eom_ccsd, n_states=0.
    draft = {"task": "single_point", "subtype": "ee", "method": "eom_ccsd", "engine": None,
             "params": {"basis": "6-31g*", "n_states": 0, "use_tda": False,
                        "want_oscillator_strengths": False}}
    v = validate_draft(draft, state, check_external=False)
    check("an eom_ccsd draft with n_states=0 reaches READY (not a crash, not a re-ask)",
          v.status == "ready", v.status)
    check("it was rerouted to single_point/gs, method='ccsd'",
          v.draft["task"] == "single_point" and v.draft["subtype"] == "gs" and v.draft["method"] == "ccsd",
          (v.draft["task"], v.draft["subtype"], v.draft["method"]))
    check("the now-inapplicable ee-only params (n_states, use_tda, want_oscillator_strengths) "
          "were dropped, not carried onto the gs approval card as stale clutter",
          not ({"n_states", "use_tda", "want_oscillator_strengths"} & v.draft["params"].keys()),
          v.draft["params"])
    check("a note explains the switch, so the model can relay it rather than silently resubmit",
          any("0 excited states" in n for n in v.notes), v.notes)

    # hf/dft: same degenerate request, but no method translation needed --
    # single_point/gs already speaks 'hf'/'dft' natively.
    draft_hf = {"task": "single_point", "subtype": "ee", "method": "hf", "engine": None,
                "params": {"basis": "sto-3g", "n_states": 0, "use_tda": False,
                           "want_oscillator_strengths": False}}
    v_hf = validate_draft(draft_hf, state, check_external=False)
    check("the same reroute applies to method='hf' (TD-HF/CIS with 0 states), landing on "
          "single_point/gs method='hf' unchanged",
          v_hf.status == "ready" and v_hf.draft["subtype"] == "gs" and v_hf.draft["method"] == "hf",
          (v_hf.status, v_hf.draft["subtype"], v_hf.draft["method"]))

    # A REAL excited-state request (n_states=2) must be completely unaffected.
    draft_real = {"task": "single_point", "subtype": "ee", "method": "eom_ccsd", "engine": None,
                  "params": {"basis": "sto-3g", "n_states": 2, "use_tda": False,
                             "want_oscillator_strengths": False}}
    v_real = validate_draft(draft_real, state, check_external=False)
    check("n_states=2 (a real excited-state request) is untouched by the reroute -- "
          "still single_point/ee, method='eom_ccsd', n_states=2",
          v_real.status == "ready" and v_real.draft["subtype"] == "ee"
          and v_real.draft["params"].get("n_states") == 2,
          v_real.draft)

    # n_states still missing entirely (no answer yet) must still ask, exactly as before.
    draft_missing = {"task": "single_point", "subtype": "ee", "method": "eom_ccsd", "engine": None,
                     "params": {"basis": "sto-3g"}}
    v_missing = validate_draft(draft_missing, state, check_external=False)
    check("n_states genuinely unanswered still asks the question (reroute only fires on an "
          "explicit 0, never on 'not answered yet')",
          v_missing.status == "incomplete" and v_missing.asking_for == "n_states",
          (v_missing.status, v_missing.asking_for))

    # CASSCF/CASPT2: n_states=0 is NOT this bug (n_states there INCLUDES the
    # ground state, so 0 is a different, pre-existing kind of malformed
    # request) -- must NOT be rerouted.
    draft_cas = {"task": "single_point", "subtype": "ee", "method": "casscf", "engine": None,
                "params": {"basis": "sto-3g", "n_states": 0, "active_electrons": 4,
                           "active_orbitals": 4}}
    v_cas = validate_draft(draft_cas, state, check_external=False)
    check("a multireference (casscf) draft with n_states=0 is NOT rerouted -- this bug is "
          "specific to single-reference methods, where n_states counts EXCITED states only",
          v_cas.draft["subtype"] == "ee" and v_cas.draft["method"] == "casscf",
          (v_cas.draft["subtype"], v_cas.draft["method"]))


def main() -> int:
    with tempfile.TemporaryDirectory() as job_dir:
        pyscf_energies = _pyscf_energy_checks(job_dir)
        _orca_energy_checks(job_dir, pyscf_energies)
    _elicitation_checks()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
