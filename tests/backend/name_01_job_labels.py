#!/usr/bin/env python3
"""A job's name identifies the calculation that produced it.

    PYTHONPATH=$PWD python3 tests/backend/name_01_job_labels.py

`resolve_job_label` is the single definition of a job's name, shared by the
Job Manager list, the drawer heading, the submission confirmation and every
download filename. That is what makes a defect here cost more than it looks
like it should: one wrong name is wrong in four places at once.

Three faults are pinned below, all reported off a real session.

- **CASSCF and CASPT2 named the same thing.** The method name was dropped
  for both, so the label carried only the active space. Two genuinely
  different calculations on one molecule came out byte-identical, which
  also meant their downloads collided in a downloads folder.
- **The task label and the method ran together**: "SPHF", "Freqb3lyp",
  "NEB-TSb3lyp".
- **snake_case identifiers leaked**: "SPEOM_CCSD" rather than "EOM-CCSD".

Pure functions, no stack, no jobs created and so none to clean up.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.chemistry.jobs.naming import (  # noqa: E402
    auto_job_name, job_filename_stem, resolve_job_label, slugify_label,
)

failures: list[str] = []
checks = 0

URACIL = {"name": "uracil", "symbols": ["C", "C", "N", "N", "O", "O"]}
WATER = {"name": "water", "symbols": ["O", "H", "H"]}


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def spec(method: str, *, task="single_point", subtype="ee", engine="bagel",
         molecule=None, **params) -> dict:
    return {"task": task, "subtype": subtype, "method": method, "engine": engine,
            "molecule": molecule or URACIL, "params": params}


def main() -> int:
    print("\n== a multireference method names itself ==")
    cas = auto_job_name(spec("casscf", active_electrons=12, active_orbitals=9, basis="cc-pvdz"))
    pt2 = auto_job_name(spec("caspt2", active_electrons=12, active_orbitals=9, basis="cc-pvdz"))
    check("CASSCF and CASPT2 do not share a name", cas != pt2, f"{cas!r} vs {pt2!r}")
    check("CASSCF says CASSCF", "CASSCF" in cas, cas)
    check("CASPT2 says CASPT2", "CASPT2" in pt2, pt2)
    check("and both still carry the active space", "(12,9)" in cas and "(12,9)" in pt2,
          f"{cas} | {pt2}")

    # The active space is optional in a draft, so the method must survive
    # without it -- this is the path that used to produce a name with no
    # level of theory in it at all.
    bare = auto_job_name(spec("casscf", basis="cc-pvdz"))
    check("a CASSCF with no active space still names the method", "CASSCF" in bare, bare)

    print("\n== the task and the level of theory are separated ==")
    cases = {
        "HF single point": auto_job_name(
            spec("hf", subtype="gs", engine="pyscf", molecule=WATER, basis="sto-3g")),
        "DFT frequencies": auto_job_name(
            spec("dft", task="freq", subtype="", engine="pyscf", molecule=WATER,
                 functional="b3lyp", basis="6-31g*")),
        "HF optimization": auto_job_name(
            spec("hf", task="opt", subtype="min", engine="pyscf", molecule=WATER, basis="sto-3g")),
        "NEB": auto_job_name(
            spec("dft", task="neb_ts", subtype="", engine="orca", molecule=WATER,
                 functional="b3lyp", basis="def2-svp")),
    }
    check("HF single point separates SP from HF", "SP HF/" in cases["HF single point"],
          cases["HF single point"])
    check("frequencies separate Freq from the functional",
          "Freq b3lyp/" in cases["DFT frequencies"], cases["DFT frequencies"])
    check("optimization separates Opt from HF", "Opt HF/" in cases["HF optimization"],
          cases["HF optimization"])
    check("NEB separates NEB-TS from the functional", "NEB-TS b3lyp/" in cases["NEB"],
          cases["NEB"])

    print("\n== no internal identifier reaches the name ==")
    eom = auto_job_name(spec("eom_ccsd", engine="pyscf", basis="cc-pvdz"))
    check("eom_ccsd is written EOM-CCSD", "EOM-CCSD" in eom, eom)
    check("and carries no underscore", "_" not in eom, eom)
    for name in [cas, pt2, eom, *cases.values()]:
        check(f"no raw task identifier in {name!r}",
              not any(t in name for t in ("single_point", "neb_ts", "opt_freq", "subtype")),
              name)

    print("\n== a user's own rename still wins ==")
    check("a stored label overrides the generated one",
          resolve_job_label(spec("casscf", basis="cc-pvdz"), {"label": "my careful run"})
          == "my careful run")
    check("and no stored label falls back to the generated one",
          resolve_job_label(spec("casscf", basis="cc-pvdz"), {}) == bare)

    print("\n== the download filename follows the name ==")
    # safename_descriptor.extension is a standing convention, so the two
    # methods must not produce the same stem either.
    stem_cas = job_filename_stem("abc123456789", spec("casscf", active_electrons=12,
                                                      active_orbitals=9, basis="cc-pvdz"), {}, 0)
    stem_pt2 = job_filename_stem("def456789012", spec("caspt2", active_electrons=12,
                                                      active_orbitals=9, basis="cc-pvdz"), {}, 0)
    check("the two stems differ by more than the job id",
          stem_cas.replace("abc123", "") != stem_pt2.replace("def456", ""),
          f"{stem_cas} | {stem_pt2}")
    check("CASSCF survives slugification", "CASSCF" in slugify_label(cas), slugify_label(cas))
    check("the slug has no spaces left", " " not in slugify_label(cas), slugify_label(cas))

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
