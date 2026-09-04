"""The lone-pair target's s amplitude, scored on both metrics at once.

P4.0 swept `geometry.LONE_PAIR_S_AMPLITUDE` against the literature space match and
found it flat, concluding the constant was not delicate. `hole_capture.py` then
swept the same constant against whether the recommended space can actually hold
the state it was sized for and found it steep, with the shipped $1/\\sqrt{3}$ at
the worst usable end. Both measurements are correct. They disagree because they
are asking about different lone pairs: a full valence space wants the s-rich
hybrid pointing away along the bond, and an n->pi* state wants the p-like one
perpendicular to it.

So neither number alone can choose the constant, and a value picked on either
one in isolation is exactly the fitted-to-one-case change that is worth nothing.
This runs both, across the whole benchmark, at every amplitude, and prints them
side by side. A value is only interesting if it improves capture without losing
literature matches, and if no such value exists then the honest conclusion is
that one constant cannot serve both and the target set has to change shape.

Note that varying the amplitude does NOT change the number of targets, so the
pool cannot inflate the way it does when a second reference is added per
direction, which is the variant `geometry.perceive` already rejects in a comment
for exactly that reason. This is a one-knob change and the only question is what
it costs.

The states-requested column drives `run_cas_recommendation` itself, the same way
`run_bench.set_narrowed` does, so it measures the production path including its
own choice of analysis basis.

Usage:
    python3 scripts/casbench/amplitude_tradeoff.py                 # full sweep
    python3 scripts/casbench/amplitude_tradeoff.py 0.0 0.577       # named values
"""
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from app.chemistry.cas import geometry                           # noqa: E402
from scripts.casbench import reference_data as ref               # noqa: E402
from scripts.casbench.run_bench import (_mf, _protocol_states)   # noqa: E402

SHIPPED = 1.0 / np.sqrt(3.0)
AMPS = [float(a) for a in sys.argv[1:]] or [0.0, 0.2, 0.35, 0.5, SHIPPED, 0.75]


def names():
    """Every molecule with a reference space, or the subset named for a probe."""
    only = os.environ.get("QC_TRADE_MOLECULES")
    all_ = [n for n in sorted(ref.REFERENCE_SPACES) if n in ref.GEOMETRIES]
    if not only:
        return all_
    want = [n.strip() for n in only.split(",") if n.strip()]
    return [n for n in all_ if n in want]


def ground_state_match(name):
    """Mirrors run_bench.set_spaces: no states requested, def2-SVP."""
    from app.chemistry.cas.recommend import recommend
    expected = tuple(ref.REFERENCE_SPACES[name][0])
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    _mol, mf = _mf(syms, co, "def2-svp", chg, mult)
    rec = recommend(mf, syms, co, spin_2s=mult - 1)
    tiers = {(t.n_electrons, t.n_orbitals) for t in rec.tiers.values()}
    if rec.space == expected:
        return "exact", rec.space
    return ("tier" if expected in tiers else "differs"), rec.space


def states_match(name):
    """Mirrors run_bench.set_narrowed: the production runner, its own basis."""
    from app.chemistry.jobs import pyscf_runner
    expected = tuple(ref.REFERENCE_SPACES[name][0])
    syms, co, chg, mult = ref.molecule(name)
    molecule = {"name": name, "symbols": list(syms),
                "coords": [[float(x) for x in c]
                           for c in np.asarray(co, float)],
                "charge": int(chg), "multiplicity": int(mult)}
    s = pyscf_runner.run_cas_recommendation(
        molecule, {"n_states": _protocol_states(name),
                   "_job_dir": tempfile.mkdtemp(),
                   "verify_active_space": False})["summary"]
    got = (s["recommended_active_electrons"],
           s["recommended_active_orbitals"])
    tiers = {tuple(v[:2]) if isinstance(v, (list, tuple)) else None
             for v in (s.get("active_space_tiers") or {}).values()}
    if got == expected:
        return "exact", got
    return ("tier" if expected in tiers else "differs"), got


def main():
    print("# The lone-pair s amplitude on both metrics, whole benchmark")
    print("")
    print(f"Shipped value is {SHIPPED:.4f}. `exact` counts a recommendation "
          f"equal to the reference space;")
    print("`+tier` additionally counts the reference appearing as one of the "
          "offered tiers.")
    print("")
    print("| s amplitude | ground state exact | ground state +tier | "
          "states exact | states +tier | seconds |")
    print("|---|---|---|---|---|---|")
    detail = {}
    for amp in AMPS:
        geometry.LONE_PAIR_S_AMPLITUDE = amp
        t0 = time.time()
        gs, st = [], []
        per_mol = {}
        for name in names():
            try:
                m, got = ground_state_match(name)
            except Exception as exc:                             # noqa: BLE001
                m, got = f"failed {type(exc).__name__}", None
            gs.append(m)
            try:
                m2, got2 = states_match(name)
            except Exception as exc:                             # noqa: BLE001
                m2, got2 = f"failed {type(exc).__name__}", None
            st.append(m2)
            per_mol[name] = (m, got, m2, got2)
        detail[amp] = per_mol
        n = len(gs)
        print(f"| {amp:.4f}{' (shipped)' if abs(amp - SHIPPED) < 1e-9 else ''} "
              f"| {gs.count('exact')}/{n} "
              f"| {gs.count('exact') + gs.count('tier')}/{n} "
              f"| {st.count('exact')}/{n} "
              f"| {st.count('exact') + st.count('tier')}/{n} "
              f"| {time.time() - t0:.0f} |")
        sys.stdout.flush()

    # Which molecules actually move, which is the part a summary count hides.
    print("")
    print("## Molecules whose verdict changes across the sweep")
    print("")
    print("| molecule | " + " | ".join(f"{a:.3f}" for a in AMPS) + " |")
    print("|---" * (len(AMPS) + 1) + "|")
    for name in names():
        gs_row = [detail[a][name][0] for a in AMPS]
        st_row = [detail[a][name][2] for a in AMPS]
        if len(set(gs_row)) > 1:
            print(f"| {name} (ground state) | "
                  + " | ".join(gs_row) + " |")
        if len(set(st_row)) > 1:
            print(f"| {name} (states) | " + " | ".join(st_row) + " |")

    geometry.LONE_PAIR_S_AMPLITUDE = SHIPPED


if __name__ == "__main__":
    main()
