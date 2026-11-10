"""Task phrases a user actually writes resolve to the task they mean.

Found on 2026-11-09 while taking the thesis screenshots: three phrasings of
a nuclear-ensemble request ("nuclear-ensemble UV/Vis spectrum ... 100 Wigner
samples" and two more) each drafted a single-geometry TDDFT job. The model
hands the user's phrase to start_job_draft verbatim, and the resolver missed
it twice over: the hyphen in "nuclear-ensemble" defeated the whole-word match,
and the longest-match rule then preferred "spectrum" or "absorption" over
"Wigner". A sample count written onto the wrong draft was refused as not a
parameter of single_point, so nothing could rescue it later either.

In-process, no stack and no model needed:

    PYTHONPATH=$PWD python3 tests/backend/draft_04_task_phrases.py
"""
from __future__ import annotations

import sys

from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import _read_phrase, validate_draft
from app.chemistry.registry2.lookup import resolve_task
from app.chemistry.registry2.params import missing_required

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


def task_of(phrase: str):
    resolved, _ = resolve_task(phrase)
    return resolved or _read_phrase(phrase)[0]


def main() -> int:
    print("== ensemble phrasings reach wigner_spectra ==")
    for phrase in ("nuclear-ensemble UV/Vis spectrum",
                   "Nuclear-ensemble spectrum (Wigner sampling)",
                   "Wigner-sampled absorption spectrum",
                   "UV-Vis spectrum from 100 Wigner samples",
                   "nuclear-ensemble", "ensemble spectrum"):
        got = task_of(phrase)
        check(f"{phrase!r} -> wigner_spectra", got == ("wigner_spectra", ""), str(got))

    print("\n== nothing else moved ==")
    for phrase, want in (("uv/vis", ("single_point", "ee")),
                         ("UV-Vis spectrum", ("single_point", "ee")),
                         ("absorption spectrum", ("single_point", "ee")),
                         ("tddft", ("single_point", "ee")),
                         ("excited state scan", ("pes_1d", "ee")),
                         ("non-adiabatic coupling", ("single_point", "nac")),
                         ("B3LYP geometry optimization", ("opt", "min")),
                         ("opt freq", ("opt_freq", ""))):
        got = task_of(phrase)
        check(f"{phrase!r} -> {want[0]}/{want[1]}", got == want, str(got))

    print("\n== a sample count turns a TDDFT draft into the ensemble ==")
    furan = resolve_molecule("furan").to_dict()
    v = validate_draft({"task": "single_point", "subtype": "ee", "method": "dft", "engine": None,
                        "params": {"basis": "def2-svp", "functional": "b3lyp",
                                   "n_excited_states": 5, "n_samples": 100}},
                       {"molecule": furan})
    check("the draft becomes wigner_spectra", v.draft["task"] == "wigner_spectra", str(v.draft))
    check("and says so", any("nuclear-ensemble spectrum" in n for n in v.notes), str(v.notes))

    print("\n== accepting n_samples on a single point does not ask for it there ==")
    gs = [p.name for p in missing_required("single_point", "gs", "hf", "pyscf", {"basis": "sto-3g"})]
    check("a ground-state single point asks for no sample count", "n_samples" not in gs, str(gs))
    wig = [p.name for p in missing_required("wigner_spectra", "", "dft", "orca",
                                            {"basis": "sto-3g", "functional": "pbe0",
                                             "n_excited_states": 5})]
    check("the ensemble still asks for one", "n_samples" in wig, str(wig))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
