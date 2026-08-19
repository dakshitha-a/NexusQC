#!/usr/bin/env python3
"""Verify registry v2's capability tables against a hand-written golden table.

    python3 scripts/check_capability_matrix.py

Read-only. Run at every phase gate and before any commit touching
`app/chemistry/registry2/`.

**The golden table below is derived from `docs/QM_CAPABILITIES.md`'s recorded
observations, not from the code it checks.** That distinction is the entire
point: a golden table generated from `capabilities.py` would agree with
`capabilities.py` by construction and prove nothing. Each expectation here
is written from what a spike actually observed -- BAGEL's `fix_atom` moving
a supposedly frozen atom, ORCA's `%casscf` rejecting `NACME`, PySCF's
missing `Hessian` attribute -- so a transcription error in the capability
table shows up as a disagreement rather than as a matching pair of mistakes.

Five checks:

1. **Golden verdicts.** Every expectation below matches `tasks.supports()`.
2. **Full cross-product.** Every (engine, method) x (task, subtype) combination
   evaluates without raising, and every refusal carries at least one reason --
   a silent "no" is a bug, because the user is owed the reason.
3. **No dangling references.** Task requirements name real capability fields,
   parameter `applies_to` entries name real tasks, engine/method allow-lists
   name real engines and methods.
4. **Evidence hygiene.** Every capability a row actually claims carries
   evidence, and every evidence source that looks like a repo path exists.
5. **Doc drift.** `generate_capability_docs.py --check` passes.

Exit code 0 = consistent, 1 = violations. Standalone invoke-and-print, per
the repo's testing conventions -- no pytest.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.chemistry.registry2.capabilities import (  # noqa: E402
    CANONICAL_METHODS, CAPABILITIES, CAPABILITY_FIELDS, ENGINES,
)
from app.chemistry.registry2.params import PARAMS  # noqa: E402
from app.chemistry.registry2.routing import route_engine  # noqa: E402
from app.chemistry.registry2.tasks import TASKS, supports  # noqa: E402

# --------------------------------------------------------------------------
# GOLDEN TABLE -- hand-written from docs/QM_CAPABILITIES.md's observations.
#
# (engine, method, task, subtype) -> expected `supported`, with the reason
# the doc gives. Do NOT regenerate this from code.
# --------------------------------------------------------------------------

GOLDEN: dict[tuple[str, str, str, str], tuple[bool, str]] = {
    # -- NAC. The inversion recorded in the doc's closing section: the
    #    single-reference engines do ground-to-excited only, and PySCF's NAC
    #    is SA-CASSCF only.
    ("pyscf", "casscf", "single_point", "nac"): (
        True, "pyscf.nac.sacasscf runs and scales as 1/dE"),
    ("pyscf", "dft", "single_point", "nac"): (
        False, "no pyscf.nac.tdscf in mainline 2.14"),
    ("pyscf", "hf", "single_point", "nac"): (
        False, "no TDDFT/CIS NAC module in pyscf 2.14"),
    ("orca", "dft", "single_point", "nac"): (
        True, "%TDDFT NACME TRUE printed couplings, norm 0.7794747730"),
    ("orca", "hf", "single_point", "nac"): (
        True, "same CIS/TDDFT module with an HF reference"),
    ("orca", "casscf", "single_point", "nac"): (
        False, "'Unknown identifier in CASSCF block ... Last token : NACME'"),
    ("bagel", "casscf", "single_point", "nac"): (
        True, "'=== NACME evaluation ===' with transition dipole and f"),
    ("bagel", "caspt2", "single_point", "nac"): (
        True, "nacme documented for caspt2, mechanism run with CASSCF"),
    ("bagel", "hf", "single_point", "nac"): (
        False, "NAC needs a multireference wavefunction"),

    # -- Constrained optimization. The differential probe settled this
    #    against BAGEL's own exit code.
    ("bagel", "casscf", "opt", "constrained"): (
        False, "fix_atom accepted, exits 0, and silently ignored"),
    ("bagel", "caspt2", "opt", "constrained"): (
        False, "same fix_atom no-op"),
    ("bagel", "hf", "opt", "constrained"): (
        False, "same fix_atom no-op"),
    ("pyscf", "hf", "opt", "constrained"): (
        True, "geomeTRIC 1.1.1 constraints kwarg, converged with the constraint"),
    ("pyscf", "casscf", "opt", "constrained"): (
        True, "geomeTRIC drives CASSCF's analytic gradient"),
    ("orca", "hf", "opt", "constrained"): (
        True, "%geom Constraints {B 0 1 0.98 C} converged"),

    # -- Conical intersection. ORCA's %CONICAL was proven with a TDDFT
    #    reference; BAGEL's MECI is the implemented multireference route;
    #    PySCF has none.
    ("pyscf", "casscf", "opt", "ci"): (
        False, "no pyscf.geomopt.meci"),
    ("pyscf", "dft", "opt", "ci"): (
        False, "no MECI optimizer in pyscf"),
    ("orca", "dft", "opt", "ci"): (
        True, "%CONICAL METHOD UBP accepted and terminated normally"),
    ("orca", "casscf", "opt", "ci"): (
        False, "%CONICAL verified with a TDDFT reference only, not CASSCF"),
    ("bagel", "casscf", "opt", "ci"): (
        True, "gradient-projection MECI, already implemented by bagel_runner"),
    ("bagel", "caspt2", "opt", "ci"): (
        True, "same MECI driver"),

    # -- Frequencies. PySCF CASSCF is numerical-only; MP2 has no Hessian
    #    wired up; ORCA CCSD has no gradient here.
    ("pyscf", "hf", "freq", ""): (True, "analytic Hessian, 3 modes max 4812.5 cm-1"),
    ("pyscf", "casscf", "freq", ""): (
        True, "numerical Hessian -- the app's own, since pyscf has no analytic one"),
    ("pyscf", "mp2", "freq", ""): (False, "no MP2 Hessian wired up here"),
    ("orca", "hf", "freq", ""): (True, "! Opt Freq produced VIBRATIONAL FREQUENCIES"),
    ("orca", "ccsd", "freq", ""): (False, "no CCSD gradient/Hessian wired up here"),
    ("bagel", "casscf", "freq", ""): (True, "hessian block produced the frequency table"),

    # -- Excited states.
    ("pyscf", "dft", "single_point", "ee"): (True, "TDDFT and TDA both produced 3 states"),
    ("pyscf", "eom_ccsd", "single_point", "ee"): (True, "EOMEESinglet returns energies"),
    ("pyscf", "mp2", "single_point", "ee"): (False, "MP2 is ground state only"),
    ("orca", "eom_ccsd", "single_point", "ee"): (True, "MDCI EOM-CCSD with transition dipoles"),
    ("bagel", "caspt2", "single_point", "ee"): (True, "nstate in the smith block"),
    ("bagel", "hf", "single_point", "ee"): (False, "HF has no excited states of its own"),

    # -- Gradients.
    ("pyscf", "ccsd", "single_point", "grad"): (True, "cc.CCSD nuc_grad_method ran"),
    ("orca", "ccsd", "single_point", "grad"): (False, "no CCSD gradient wired up here"),
    ("bagel", "casscf", "single_point", "grad"): (True, "'forces' block, Nuclear energy gradient"),

    # -- Engine-scoped tasks.
    ("orca", "dft", "neb_ts", ""): (True, "ORCA is the only engine with a native NEB-TS"),
    ("pyscf", "dft", "neb_ts", ""): (False, "no NEB implementation in pyscf here"),
    ("bagel", "casscf", "neb_ts", ""): (False, "no NEB implementation in bagel here"),
    ("pyscf", "casscf", "cas_reco", "autocas"): (
        True, "AVAS + entropy pilot need in-memory pyscf objects"),
    ("orca", "casscf", "cas_reco", "autocas"): (
        False, "no round-trippable in-memory RDM/mo_coeff access"),
    ("orca", None, "blind", ""): (True, "ORCA has a literal input-file format"),
    ("bagel", None, "blind", ""): (True, "BAGEL takes a literal JSON input"),
    ("pyscf", None, "blind", ""): (
        False, "no user-supplied Python ever executes -- the user's standing decision"),
}

# Expected routing outcomes, likewise hand-written from the recorded rules.
GOLDEN_ROUTING: dict[tuple[str, str, str], tuple[str, str]] = {
    ("caspt2", "single_point", "ee"): ("bagel", "BAGEL is the only CASPT2 here"),
    ("casscf", "single_point", "ee"): ("pyscf", "preference order, no rule fires"),
    ("hf", "single_point", "gs"): ("pyscf", "preference order"),
    ("dft", "single_point", "nac"): ("orca", "pyscf has no TDDFT NAC, so ORCA wins"),
    ("casscf", "opt", "ci"): ("bagel", "the only verified MECI route"),
}


def main() -> int:
    errors: list[str] = []
    checked = 0

    # 1 -- golden verdicts
    for (engine, method, task, subtype), (expected, why) in GOLDEN.items():
        actual = supports(engine, method, task, subtype)
        checked += 1
        if actual.supported != expected:
            name = f"{task}/{subtype}" if subtype else task
            errors.append(
                f"golden mismatch: {engine}/{method} {name} -- expected "
                f"supported={expected} ({why}), got {actual.supported}"
                + (f" reasons={list(actual.reasons)}" if actual.reasons else "")
            )
        if not expected and not actual.reasons:
            errors.append(
                f"silent refusal: {engine}/{method} {task}/{subtype} is unsupported "
                f"but gives no reason"
            )

    # 1b -- golden routing
    for (method, task, subtype), (expected_engine, why) in GOLDEN_ROUTING.items():
        decision = route_engine(method, task, subtype)
        checked += 1
        if decision.engine != expected_engine:
            errors.append(
                f"golden routing mismatch: {method} {task}/{subtype} -- expected "
                f"{expected_engine} ({why}), got {decision.engine}"
            )

    # 2 -- full cross-product evaluates, and refusals explain themselves
    for engine in ENGINES:
        for method in list(CANONICAL_METHODS) + [None]:
            for (task, subtype) in TASKS:
                checked += 1
                try:
                    verdict = supports(engine, method, task, subtype)
                except Exception as exc:  # noqa: BLE001 -- reporting, not handling
                    errors.append(
                        f"supports({engine}, {method}, {task}, {subtype}) raised "
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue
                if not verdict.supported and not verdict.reasons:
                    errors.append(
                        f"silent refusal: {engine}/{method} {task}/{subtype}"
                    )

    # 3 -- no dangling references
    for (task, subtype), tdef in TASKS.items():
        for capability in tdef.requires:
            if capability not in CAPABILITY_FIELDS:
                errors.append(
                    f"task {task}/{subtype} requires unknown capability {capability!r}"
                )
        for engine in tdef.engines or ():
            if engine not in ENGINES:
                errors.append(f"task {task}/{subtype} allows unknown engine {engine!r}")
        for method in tdef.methods or ():
            if method not in CANONICAL_METHODS:
                errors.append(f"task {task}/{subtype} allows unknown method {method!r}")

    task_names = {t for t, _ in TASKS} | {f"{t}/{s}" if s else t for t, s in TASKS}
    for spec in PARAMS:
        if not spec.applies_to:
            errors.append(f"param {spec.name!r} applies to no task")
        for entry in spec.applies_to:
            if entry not in task_names:
                errors.append(
                    f"param {spec.name!r} applies_to unknown task {entry!r}"
                )

    # 4 -- evidence hygiene
    for (engine, method), caps in CAPABILITIES.items():
        for capability in CAPABILITY_FIELDS:
            value = getattr(caps, capability)
            if value is None or value is False:
                continue
            if capability not in caps.evidence:
                errors.append(
                    f"{engine}/{method} claims {capability!r} with no evidence"
                )
        for capability, ev in caps.evidence.items():
            if capability not in CAPABILITY_FIELDS:
                errors.append(
                    f"{engine}/{method} has evidence for unknown field {capability!r}"
                )
            # Only sources that are committed to the repository are checked
            # for existence. `data/scraped/` is the locally seeded manual
            # corpus -- nothing under `data/` is tracked beyond its
            # .gitkeep files -- so asserting it exists would make this
            # check pass on a seeded host and fail in a fresh clone or a
            # worktree, which is exactly the kind of environment-dependent
            # test the repo's conventions avoid.
            source = ev.source
            if source.startswith("scripts/") and not (REPO / source).exists():
                errors.append(
                    f"{engine}/{method} {capability}: evidence source {source!r} "
                    f"does not exist"
                )

    # 5 -- doc drift
    drift = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_capability_docs.py"), "--check"],
        cwd=REPO, capture_output=True, text=True,
    )
    checked += 1
    if drift.returncode != 0:
        errors.append("docs/QM_CAPABILITIES.md is out of date -- run "
                      "scripts/generate_capability_docs.py")

    print(f"checked {checked} assertions across {len(CAPABILITIES)} capability rows "
          f"and {len(TASKS)} tasks")
    if errors:
        print(f"\n[FAIL] {len(errors)} violation(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("[PASS] capability matrix consistent with the golden table, no dangling "
          "references, docs in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
