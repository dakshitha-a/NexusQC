#!/usr/bin/env python3
"""cas_reco/avas runs AVAS, not the AutoCAS entropy pipeline wearing its
name.

`dispatch.py` used to map all three cas_reco subtypes -- explain, autocas
and avas -- to the single `recommend_active_space` runner, and
`pyscf_runner.py` contained no reference to `subtype` at all. So the
registry advertised three capabilities with three descriptions and
delivered one. `cas_reco/avas` is documented as building a space from
atomic-valence character labels and ran the full entropy pipeline instead.

Nobody chose that. The runner was written for AutoCAS, in which AVAS is the
*pilot seeder* -- the entropy screen needs a candidate valence pool and AVAS
is the standard way to get one. Registry v2's dark-launch later declared
three subtypes as taxonomy without implementing them, and the dispatch table
the next day needed a runner for every declared pair and had exactly one to
give. The same commit introduced NOT_YET_IMPLEMENTED, which is where the two
unbuilt ones belonged.

What this checks is that asking for AVAS now gets AVAS: its own runner, no
entropy screening anywhere in its output, and -- the point of the split -- a
different answer from AutoCAS on the same molecule.

Needs PySCF but no live stack.

Run:  PYTHONPATH=$PWD python3 tests/backend/casreco_03_avas_subtype.py
"""
from __future__ import annotations

import sys
import tempfile

from app.chemistry.jobs.dispatch import resolve_runner
from app.chemistry.jobs.pyscf_runner import (
    build_input_preview, run_avas_active_space, run_recommend_active_space,
)
from app.chemistry.jobs.pyscf_worker import DISPATCH

PASS = 0
FAIL = 0

WATER = {
    "name": "water", "symbols": ["O", "H", "H"],
    "coords": [[0, 0, 0.117], [0, 0.757, -0.469], [0, -0.757, -0.469]],
    "charge": 0, "multiplicity": 1,
}
ENTROPY_FIELDS = ("entropy_method", "dmrg_bond_dim", "pilot_space_orbitals",
                  "pilot_space_truncated", "entropy_threshold_used", "plateau_found",
                  "pilot_orbital_entropies")


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def run_dispatch() -> None:
    print("\n== the two subtypes reach two runners ==")
    avas_key, _ = resolve_runner("cas_reco", "avas", "casscf")
    auto_key, _ = resolve_runner("cas_reco", "autocas", "casscf")
    check("cas_reco/avas routes to avas_active_space", avas_key == "avas_active_space",
          repr(avas_key))
    check("cas_reco/autocas still routes to recommend_active_space",
          auto_key == "recommend_active_space", repr(auto_key))
    check("they are not the same runner", avas_key != auto_key)
    check("the worker can dispatch both",
          DISPATCH.get(avas_key) is not None and DISPATCH.get(auto_key) is not None)


def run_preview() -> None:
    print("\n== the approval card describes the pipeline that will run ==")
    avas_text = build_input_preview("avas_active_space", WATER,
                                    {"basis": "cc-pvdz", "n_states": 1})
    auto_text = build_input_preview("recommend_active_space", WATER,
                                    {"basis": "cc-pvdz", "n_states": 1})
    check("the two previews differ", avas_text != auto_text)
    for word in ("plateau", "CASCI"):
        check(f"the AVAS preview does not promise a {word} step",
              word.lower() not in avas_text.lower(), avas_text)
    # Not merely silent about screening -- the card says outright that none
    # happens, because that absence IS what the user chose when they asked
    # for AVAS rather than AutoCAS.
    check("the AVAS preview states that no entropy screening happens",
          "no entropy screening" in avas_text.lower(), avas_text)
    check("the AutoCAS preview still describes its entropy pilot",
          "entrop" in auto_text.lower())
    check("the AVAS preview points at AutoCAS for the screened alternative",
          "AutoCAS" in avas_text, avas_text)


def run_results() -> None:
    print("\n== an AVAS job reports an AVAS result ==")
    with tempfile.TemporaryDirectory() as d:
        avas = run_avas_active_space(
            WATER, {"basis": "cc-pvdz", "n_states": 1, "method": "casscf", "_job_dir": d})
    s = avas["summary"]
    for field in ENTROPY_FIELDS:
        check(f"no '{field}' in an AVAS summary", field not in s, repr(s.get(field)))
    check("no entropy plateau artifact is produced",
          "entropy_plateau" not in avas["artifacts"], repr(list(avas["artifacts"])))
    check("the space AVAS selected is reported", s.get("avas_orbitals_selected") is not None)
    check("...along with the labels it used", bool(s.get("avas_aolabels_used")),
          repr(s.get("avas_aolabels_used")))
    check("the findings say no screening was applied",
          "No entropy screening" in s["findings_summary"], s["findings_summary"])
    check("the shared recommendation fields the UI reads are still present",
          s.get("recommended_active_electrons") is not None
          and s.get("recommended_active_orbitals") is not None
          and s.get("active_space_orbital_indices"),
          repr({k: s.get(k) for k in ("recommended_active_electrons",
                                      "recommended_active_orbitals")}))

    print("\n== the two algorithms give different answers, which is the point ==")
    with tempfile.TemporaryDirectory() as d:
        auto = run_recommend_active_space(
            WATER, {"basis": "cc-pvdz", "n_states": 1, "method": "casscf", "_job_dir": d})
    a = (s["recommended_active_electrons"], s["recommended_active_orbitals"])
    b = (auto["summary"]["recommended_active_electrons"],
         auto["summary"]["recommended_active_orbitals"])
    check(f"AVAS {a[0]}e,{a[1]}o differs from AutoCAS {b[0]}e,{b[1]}o on the same molecule",
          a != b, f"both returned {a} -- the subtypes may still share a path")
    check("AVAS's space is the larger one, being unscreened", a[1] >= b[1],
          f"avas={a}, autocas={b}")


def main() -> int:
    run_dispatch()
    run_preview()
    run_results()
    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
