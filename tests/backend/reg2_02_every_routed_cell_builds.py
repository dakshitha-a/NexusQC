#!/usr/bin/env python3
"""Every cell the registry routes has a builder that will accept it.
Regression test for R-028.

    PYTHONPATH=$PWD python3 tests/backend/reg2_02_every_routed_cell_builds.py

`registry2` is the single source of truth for which engine runs which method
on which task -- CLAUDE.md says so, ARCHITECTURE.md says `supports()` "is
derived from that pairing and is never hand-enumerated", and the elicitation
layer, the routing layer and the capability documentation all read it.

The input builders did not. `orca_runner._method_line` refused anything but
hf and dft; `pyscf_runner.build_mf` the same; `bagel_runner` accepted only
casscf and caspt2 for an optimisation. Those are hardcoded capability claims
of exactly the kind the registry exists to replace, and they had drifted from
it in ten places: `supports()` returned True, `route_engine()` actively chose
an engine, `validate_draft` returned `ready`, the approval card was raised and
approved, and the job died at input building with "Unsupported method".

So this walks every (task, subtype, method, engine) cell the registry claims
and asks the builder to build it. It is a compile-time question, not a
chemistry one: nothing is submitted, nothing runs, no engine binary is
touched. A cell that raises is either a registry row that overclaims or a
builder that has not caught up, and either way the two disagree, which is the
thing being tested.

Two kinds of failure are excluded, deliberately and by name:

- A missing REQUIRED PARAMETER. The fixture below supplies a plausible value
  for every parameter the registry declares, but a task with an unusual one
  would fail for a reason that has nothing to do with capability drift. Those
  are reported as skips, with the parameter named.
- Master tasks (batch, pes_1d, interp_pes, wigner_spectra, geometry_set),
  which have no single input to build; their per-image children are covered
  by the ordinary cells.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, skip, summary  # noqa: E402

from app.chemistry.jobs.base import JobSpec  # noqa: E402
from app.chemistry.jobs.preview import build_input_preview  # noqa: E402
from app.chemistry.registry2.capabilities import CANONICAL_METHODS, ENGINES  # noqa: E402
from app.chemistry.registry2.lookup import route_engine, supports  # noqa: E402
from app.chemistry.registry2.tasks import TASKS  # noqa: E402

WATER = {
    "name": "water", "identifier": "water",
    "symbols": ["O", "H", "H"],
    "coords": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.96], [0.93, 0.0, -0.24]],
    "charge": 0, "multiplicity": 1,
}

# One plausible value per parameter any task might declare. Not a
# capability statement: it exists so a cell fails for the reason under test
# rather than for a missing key.
PARAMS = {
    "basis": "sto-3g", "functional": "b3lyp",
    "active_electrons": 4, "active_orbitals": 4, "n_states": 2,
    "on_functional": "tPBE", "ot_functional": "tPBE",
    "target_states": [1], "state_pairs": [[1, 2]],
    "n_excited_states": 1, "use_tda": False,
    "max_steps": 50, "n_points": 3, "n_images": 3, "n_samples": 2,
    "scan_range": [0.9, 1.1], "coordinate": "1-2",
    "temperature_K": 300.0, "broadening_eV": 0.1,
}

MASTERS = {"batch", "pes_1d", "interp_pes", "wigner_spectra", "geometry_set"}
# A blind job has no level of theory at all -- its spec carries method="" and
# the user's own engine text -- so pairing it with each canonical method is a
# fixture artifact rather than a cell anyone can request. R-028's own scope
# line excludes the same rows for the same reason.
NO_METHOD_TASKS = {"blind"}

print("R-028: every routed cell has a builder that accepts it\n")

routed = 0
built = 0
broken: list[str] = []
skipped: list[str] = []

for (task, subtype) in sorted(TASKS):
    if task in MASTERS or task in NO_METHOD_TASKS:
        continue
    for method in CANONICAL_METHODS:
        for engine in ENGINES:
            if not supports(engine, method, task, subtype):
                continue
            decision = route_engine(method, task, subtype, requested_engine=engine)
            if decision.engine != engine:
                continue
            routed += 1
            cell = f"{task}/{subtype or '-'} {method} on {engine}"
            spec = JobSpec(task=task, subtype=subtype, method=method, engine=engine,
                           molecule=dict(WATER), params=dict(PARAMS))
            try:
                text = build_input_preview(spec)
            except Exception as exc:                            # noqa: BLE001
                msg = str(exc)
                if "requires" in msg and "parameter" in msg:
                    skipped.append(f"{cell}: {msg[:90]}")
                else:
                    broken.append(f"{cell}: {type(exc).__name__}: {msg[:110]}")
                continue
            if not (text or "").strip():
                broken.append(f"{cell}: the builder returned an empty input")
                continue
            built += 1

print(f"{routed} routed cell(s); {built} built, {len(broken)} refused, "
      f"{len(skipped)} skipped for a missing parameter\n")

for s in skipped:
    skip(s.split(":")[0], s.split(":", 1)[1].strip())

check(f"every one of the {routed} routed cells builds an input",
      not broken, f"{built}/{routed}",
      "\n        " + "\n        ".join(broken))

print("\nA blind job previews as the text the user wrote:")
blind = JobSpec(task="blind", subtype="", method="", engine="orca",
                molecule=dict(WATER), params={"_raw_input": "! HF sto-3g\n* xyz 0 1\nO 0 0 0\n*"})
try:
    check("build_input_preview returns a blind job's own input",
          build_input_preview(blind).startswith("! HF"), "")
except Exception as exc:                                        # noqa: BLE001
    check("build_input_preview returns a blind job's own input", False, "",
          f"{type(exc).__name__}: {exc}")

print("\nAnd the two specific routings R-028 named:")
from app.chemistry.jobs.dispatch import resolve_runner  # noqa: E402

runner, err = resolve_runner("single_point", "gs", "eom_ccsd")
check("single_point/gs with eom_ccsd resolves to the eom_ccsd runner",
      runner == "eom_ccsd", f"{runner!r} ({err})",
      "it resolves to the plain single_point runner, which then rejects the "
      "method -- the eom_ccsd branch was gated on subtype == 'ee'")
runner, err = resolve_runner("single_point", "ee", "eom_ccsd")
check("and so does single_point/ee", runner == "eom_ccsd", f"{runner!r} ({err})")

summary()
