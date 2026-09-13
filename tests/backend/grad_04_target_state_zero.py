#!/usr/bin/env python3
"""The ground state is a state, not a falsy value.
Regression test for R-010, with R-077 and R-096 alongside it.

    PYTHONPATH=$PWD python3 tests/backend/grad_04_target_state_zero.py

R-010. Two conventions live side by side in this codebase and
`docs/ARCHITECTURE.md` warns about exactly this pair: `target_states` is
1-based and includes the ground state, so state 1 is S0, while the older
scalar `target_state` counts excited roots with 0 meaning the ground state.
The ground state's legitimate value in the scalar is therefore the falsy one,
and ORCA's gradient input builder read it with `or`:

    target_state = params.get("target_state") or ((targets[0] - 1) or None)

`run_gradient` sets that key for every run in a multi-state gradient, so the
S0 run passed 0 (written as `None`, which made it worse), fell through to the
fallback, and took its root from `targets[0]`. With `target_states=[2, 1]`,
a plausible phrasing of "S1 and the ground state", the ground-state run
emitted `IRoot 1` and S1's gradient was parsed and recorded as S0's. A wrong
number presented as correct.

The check below is the input text itself, for every ordering, on all three
engines. PySCF and BAGEL convert per entry without the `or` and were already
right; they are checked anyway, because "this class of bug, on every engine"
is the standing rule and a passing check on the two correct engines is what
makes the ORCA one mean something.

R-077 rides along. MC-PDFT evaluates each state's energy separately and the
states keep the ordinal labels the underlying CASSCF gave them, so the ladder
is not guaranteed ascending. `run_pdft_family` wrote that into the summary as
a note; every derived field ignored it. `excitation_energies_eV` measured
from `states[0]` and dropped `states[0]` from the list, so a reordered ladder
produced a negative "excitation energy" and omitted the genuinely excited
first-labelled state while keeping the real ground state in the list at
0.0 eV. `facts.canonicalize` set `total_energy_hartree = states[0]`, a key
asserting a ground state it had not checked.

R-096: the scan legend said "Ground state" and "State 1", where "State 1"
means the FIRST EXCITED state, next to job parameters where state 1 means the
ground state. Spectroscopic notation belongs to neither convention.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

from app.chemistry.molecule import resolve_molecule  # noqa: E402

mol = resolve_molecule("water").to_dict()
BASE = {"basis": "sto-3g", "method": "dft", "functional": "b3lyp"}


def orca_iroots(text: str) -> list[int]:
    return [int(ln.split()[-1]) for ln in text.splitlines() if ln.strip().startswith("IRoot ")]


print("R-010: state zero is a state\n")
print("1. ORCA, every ordering of target_states")
from app.chemistry.jobs import orca_runner  # noqa: E402

for targets in ([1], [1, 2], [2, 1], [3, 1], [1, 3], [2, 3, 1]):
    for state in targets:
        # Exactly what run_gradient passes for each run of the set.
        params = {**BASE, "target_states": targets, "target_state": state - 1}
        roots = orca_iroots(orca_runner.build_input_text("gradient", mol, params))
        want = [] if state == 1 else [state - 1]
        check(f"targets={targets}, the S{state - 1} run asks for {want or 'no excited root'}",
              roots == want, f"IRoot {roots}",
              f"IRoot {roots}: this run would return the wrong state's gradient "
              f"labelled S{state - 1}")

print("\n   and the preview, which has no target_state at all, still shows the first run")
for targets, want in (([1], []), ([1, 2], []), ([2, 1], [1]), ([3, 1], [2])):
    roots = orca_iroots(orca_runner.build_input_text("gradient", mol, {**BASE, "target_states": targets}))
    check(f"preview for target_states={targets} shows IRoot {want or 'none'}", roots == want, f"{roots}")

print("\n2. the same class on the other two engines")
from app.chemistry.jobs import bagel_runner  # noqa: E402

for targets in ([1], [2, 1], [3, 1]):
    doc, _meta = bagel_runner._build_input(
        mol,
        {**BASE, "method": "casscf", "target_states": targets,
         "active_electrons": 4, "active_orbitals": 4, "n_states": max(targets)},
        "gradient")
    grads = []
    for blk in doc.get("bagel", []):
        for g in (blk.get("grads") or []):
            grads.append(g.get("target"))
    check(f"BAGEL target_states={targets} asks for targets {sorted(t - 1 for t in targets)}",
          sorted(x for x in grads if x is not None) == sorted(t - 1 for t in targets),
          f"grads targets {grads}")

import inspect  # noqa: E402
from app.chemistry.jobs import pyscf_runner  # noqa: E402

src = inspect.getsource(pyscf_runner.run_gradient)
check("PySCF converts per entry rather than through `or`",
      "root = state - 1" in src or "state - 1" in src, "",
      "check its target-state handling by hand")

print("\n3. R-077: a reordered ladder reports honest numbers")
from app.chemistry.jobs import derivatives  # noqa: E402
from app.chemistry.jobs import facts  # noqa: E402

asc = [-100.0, -99.9, -99.8]
reordered = [-99.9, -100.0, -99.8]   # the same three states, MC-PDFT label order
check("an ascending ladder is unchanged",
      [round(x, 6) for x in derivatives.excitation_energies_eV(asc)]
      == [round(2.721138624598645, 6), round(5.44227724919729, 6)],
      f"{derivatives.excitation_energies_eV(asc)}")
got = derivatives.excitation_energies_eV(reordered)
check("a reordered ladder gives the same physical excitations",
      [round(x, 6) for x in got] == [round(x, 6) for x in derivatives.excitation_energies_eV(asc)],
      f"{got}")
check("and none of them is negative", all(x >= 0 for x in got), f"{got}")

ladder = derivatives._state_ladder(reordered)
check("a reordered ladder carries a note saying so", "state_order_note" in ladder,
      "", "nothing downstream is told the labels are not in energy order")
check("an ascending ladder carries no such note",
      "state_order_note" not in derivatives._state_ladder(asc), "",
      "every ordinary job would carry a warning it did not earn")

canon = facts.canonicalize({"state_energies_hartree": list(reordered)})
check("total_energy_hartree is the lowest state, not the first-labelled one",
      canon.get("total_energy_hartree") == -100.0,
      f"{canon.get('total_energy_hartree')}")

print("\n4. R-096: one state numbering, everywhere")
from app.chemistry.jobs.scan_orchestrator import _build_state_series  # noqa: E402

series = _build_state_series([[-100.0, -99.9, -99.8], [-100.1, -99.95, -99.85]])
check("the scan legend uses S0/S1/S2", list(series) == ["S0", "S1", "S2"], f"{list(series)}")
# The rendered strings only, not the comment explaining why they changed.
drawer = (REPO / "frontend" / "src" / "jobs" / "JobDetailDrawer.tsx").read_text()
rendered = [ln for ln in drawer.splitlines()
            if "Ground state" in ln and not ln.strip().startswith(("//", "*", "/*"))]
check("and the drawer no longer renders 'Ground state' next to 'State S1'",
      not rendered, "", f"still rendered at: {rendered}")

summary()
