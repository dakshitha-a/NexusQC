"""How much does the same calculation move when you run it again?

Phase 0 of the CAS engine audit. `docs/CAS_ENGINE_METHOD.md` section 11.4
records three identical repeats of acrolein's SA-CASSCF giving three energies
and one non-convergence, with the root nearest its 6.68 eV reference moving
0.29 eV, and tells the reader to treat any per-state difference below about
0.3 eV as not measured. Every accuracy change worth making to the selector is
smaller than that, so the floor has to be understood before anything else can
be evaluated.

This script measures the floor rather than asserting it, and it records the
CHARACTER of every root alongside the energy. That is the part the original
table was missing and it is what makes the number interpretable. In the
recorded run the ground-state energy moved 0.1 mHartree, which is 0.003 eV,
while root 5 moved 0.29 eV. A hundredfold difference between those two is not
one state's energy wobbling around a minimum. Either a different state landed
at root 5, or the state average settled on a different solution whose sixth
root is a different state. Only the characters separate those two, and they
answer different questions: the first is a state-matching artefact of the
benchmark and costs nothing in the product, the second is a real
irreproducibility a user would see.

Protocols are named rather than hardcoded so the bisection is a matter of
running this again with a different `--protocol`, and so whatever is found can
be quoted with the settings that produced it. Thread count is NOT a protocol
option: BLAS reads it before numpy is imported, so it has to be set in the
environment of the process and is recorded here rather than set here.

Usage:

    PYTHONPATH=$PWD python3 -u scripts/casbench/repeat_scatter.py \
        --molecule acrolein --repeats 5 --protocol harness

    OMP_NUM_THREADS=1 PYTHONPATH=$PWD python3 -u \
        scripts/casbench/repeat_scatter.py --molecule acrolein --protocol serial
"""
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.casbench import reference_data as ref                # noqa: E402
from scripts.casbench.run_bench import recommend_new              # noqa: E402


HARTREE_EV = 27.211386245988

# Each protocol is a complete statement of how the CASSCF was converged, so a
# number quoted from this script can always be traced to one. "harness" is what
# `run_bench.set_nevpt2` does today, including its Newton retry, and is the
# control: the method document says the harness "now converges harder before
# reporting", so the first question is whether the recorded 0.29 eV survives
# the hardening that was already done. "loose" is what `refine._solve` uses,
# which is the setting the product actually ships.
PROTOCOLS = {
    "harness": dict(conv_tol=1e-8, conv_tol_grad=1e-5, max_macro=100,
                    newton_retry=True),
    "loose": dict(conv_tol=1e-6, conv_tol_grad=1e-4, max_macro=50,
                  newton_retry=False),
    "tight": dict(conv_tol=1e-10, conv_tol_grad=1e-7, max_macro=300,
                  newton_retry=True),
    "serial": dict(conv_tol=1e-8, conv_tol_grad=1e-5, max_macro=100,
                   newton_retry=True),
}


def _targets(name):
    from app.chemistry.cas.geometry import perceive
    syms, co, _chg, _mult = ref.molecule(name)
    per = perceive(syms, np.asarray(co, float), include_sigma=False)
    return ([t for t in per.targets if t.kind == "pi"],
            [t for t in per.targets if t.kind == "lone_pair"])


def one_trial(name, basis, nroots, proto):
    """One complete run, from a fresh SCF through to characterised roots."""
    from pyscf import mcscf

    from app.chemistry.cas import feasibility
    from app.chemistry.cas.refine import _root_characters, _spin_adapt

    t0 = time.time()
    rec, _dt, mol, mf = recommend_new(name, basis=basis)
    ne, no = rec.space

    nroots = min(nroots, feasibility.assess(no, ne).n_csf)

    mc = mcscf.CASSCF(mf, no, ne)
    _spin_adapt(mc, mol)
    mc.fcisolver.nroots = nroots
    mc.state_average_([1.0 / nroots] * nroots)
    mc.max_cycle_macro = proto["max_macro"]
    mc.conv_tol = proto["conv_tol"]
    mc.conv_tol_grad = proto["conv_tol_grad"]
    mc.kernel(rec.mo_coeff)

    retried = False
    if not mc.converged and proto["newton_retry"]:
        try:
            mc2 = mc.newton()
            mc2.max_cycle_macro = proto["max_macro"]
            mc2.kernel(mc.mo_coeff)
            if mc2.converged or (float(np.asarray(mc2.e_states)[0])
                                 < float(np.asarray(mc.e_states)[0])):
                mc, retried = mc2, True
        except Exception:                                       # noqa: BLE001
            pass

    e = np.asarray(mc.e_states, dtype=float)
    pi_t, lp_t = _targets(name)
    chars = _root_characters(mc, mol, pi_t, lp_t)

    tier = rec.tiers[rec.recommended]
    return {
        "space": [int(ne), int(no)],
        "orbital_indices": [int(i) + 1 for i in tier.orbital_indices],
        "converged": bool(mc.converged),
        "newton_retry": retried,
        "e0_hartree": float(e[0]),
        "excitations_ev": [float((x - e[0]) * HARTREE_EV) for x in e[1:]],
        "root_characters": list(chars),
        "seconds": round(time.time() - t0, 1),
    }


def one_refine_trial(name, basis, n_states):
    """One complete refinement, the path a user's `cas_reco/refine` job takes.

    Mirrors `run_bench.set_refine` rather than reimplementing it, because the
    question is whether the shipped loop reproduces, not whether some other
    loop does. The refinement is where the irreproducibility actually costs
    something: its state audit compares root CHARACTERS, so a character that
    moves between identical runs changes which branch the loop takes, and the
    tracker records uracil returning (14e,9o), (14e,10o) and (14e,9o) by a
    different route across three identical runs.
    """
    from pyscf import tdscf

    from app.chemistry.cas.excited import analyse
    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.recommend import recommend
    from app.chemistry.cas.refine import refine

    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)

    t0 = time.time()
    mol, mf = _mf_for(syms, co, basis, chg, mult)
    rec = recommend(mf, syms, co, spin_2s=mult - 1, n_states=n_states)
    quick = rec.space

    an, predicted = None, []
    if mult == 1 and n_states > 1:
        _m, ks = _mf_for(syms, co, basis, chg, mult, dft_xc="camb3lyp")
        td = tdscf.TDA(ks)
        td.nstates = max(6, 2 * (n_states - 1))
        td.kernel()
        per = perceive(syms, co, include_sigma=False)
        an = analyse(ks, td, per.targets, n_states=n_states - 1)
        predicted = [s.character for s in an.states[:n_states - 1]
                     if s.particle_kind != "Rydberg"
                     and "mixed" not in s.character]
        known = getattr(ref, "REFERENCE_STATE_CHARACTERS", {}).get(name)
        if known:
            predicted = list(known[:n_states - 1])

    res = refine(mf, syms, co, rec, n_states=n_states, analysis=an,
                 predicted=predicted, spin_2s=mult - 1, log=lambda *a, **k: None)

    return {
        "quick_space": [int(quick[0]), int(quick[1])],
        "refined_space": [int(res.n_electrons), int(res.n_orbitals)],
        "converged": bool(res.converged),
        "cycles": int(res.cycles),
        "stopped_because": str(res.stopped_because),
        "actions": [r.action for r in res.rotations],
        "excitations_ev": [round(float(x), 4) for x in res.energies_ev],
        "root_characters": list(res.characters),
        "orbital_labels": list(res.orbital_labels),
        "seconds": round(time.time() - t0, 1),
    }


def _mf_for(syms, co, basis, charge, mult, dft_xc=None):
    from scripts.casbench.run_bench import _mf
    return _mf(syms, co, basis, charge, mult, dft_xc=dft_xc)


def _report_refine(ok):
    spaces = {tuple(t["refined_space"]) for t in ok}
    print(f"refined space:  {len(spaces)} distinct {sorted(spaces)}"
          f"  -> {'STABLE' if len(spaces) == 1 else 'UNSTABLE'}", flush=True)
    acts = {tuple(t["actions"]) for t in ok}
    print(f"rotation trail: {len(acts)} distinct"
          f"  -> {'STABLE' if len(acts) == 1 else 'UNSTABLE'}", flush=True)
    for a in sorted(acts):
        print(f"                {list(a)}", flush=True)
    chars = {tuple(t["root_characters"]) for t in ok}
    print(f"root characters:{len(chars)} distinct"
          f"  -> {'STABLE' if len(chars) == 1 else 'UNSTABLE'}", flush=True)
    for c in sorted(chars):
        print(f"                {list(c)}", flush=True)
    labels = {tuple(t["orbital_labels"]) for t in ok}
    print(f"orbital labels: {len(labels)} distinct"
          f"  -> {'STABLE' if len(labels) == 1 else 'UNSTABLE'}", flush=True)
    nconv = sum(1 for t in ok if t["converged"])
    print(f"converged:      {nconv}/{len(ok)}", flush=True)
    print(f"seconds:        {[t['seconds'] for t in ok]}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--molecule", default="acrolein")
    ap.add_argument("--mode", default="casscf", choices=("casscf", "refine"),
                    help="casscf: a bare SA-CASSCF in the recommended space. "
                         "refine: the whole shipped refinement loop.")
    ap.add_argument("--n-states", type=int, default=None,
                    help="refine mode only; defaults to the reference "
                         "protocol for this molecule")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--basis", default="cc-pvdz")
    ap.add_argument("--protocol", default="harness", choices=sorted(PROTOCOLS))
    ap.add_argument("--extra-roots", type=int, default=3)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    name = args.molecule
    refs = ref.EXCITATIONS.get(name, [])
    valence = [r for r in refs if "Rydberg" not in r[1]]
    nroots = len(valence) + 1 + args.extra_roots

    n_states = args.n_states
    if n_states is None:
        n_ref = len(ref.EXCITATIONS.get(name, []))
        n_char = len(getattr(ref, "REFERENCE_STATE_CHARACTERS", {}).get(name, []))
        n_states = getattr(ref, "PROTOCOL_STATES", {}).get(name)
        if n_states is None:
            n_states = min(3, max(n_ref, n_char) + 1) if (n_ref or n_char) else 1

    proto = PROTOCOLS[args.protocol]
    threads = os.environ.get("OMP_NUM_THREADS", "unset")
    if args.mode == "refine":
        print(f"# scatter: {name} / {args.basis} / mode=refine / "
              f"n_states={n_states} / OMP_NUM_THREADS={threads}", flush=True)
        print("# the shipped refinement loop; its tolerances live in "
              "refine._solve, not in --protocol", flush=True)
    else:
        print(f"# scatter: {name} / {args.basis} / protocol={args.protocol} / "
              f"{nroots} roots / OMP_NUM_THREADS={threads}", flush=True)
        print(f"# {proto}", flush=True)

    trials = []
    for k in range(1, args.repeats + 1):
        try:
            if args.mode == "refine":
                row = one_refine_trial(name, args.basis, n_states)
            else:
                row = one_trial(name, args.basis, nroots, proto)
        except Exception as exc:                                # noqa: BLE001
            row = {"error": f"{type(exc).__name__}: {exc}"}
        row["trial"] = k
        trials.append(row)
        print(f"trial {k}: {json.dumps(row)}", flush=True)

    ok = [t for t in trials if "error" not in t]
    if ok and args.mode == "refine":
        print("", flush=True)
        print("## spread", flush=True)
        _report_refine(ok)
    elif ok:
        print("", flush=True)
        print("## spread", flush=True)
        spaces = {tuple(t["space"]) for t in ok}
        print(f"space:      {len(spaces)} distinct {sorted(spaces)}"
              f"  -> {'STABLE' if len(spaces) == 1 else 'UNSTABLE'}", flush=True)
        e0 = [t["e0_hartree"] for t in ok]
        print(f"E0 spread:  {(max(e0) - min(e0)) * HARTREE_EV * 1000:.3f} meV"
              f"  ({max(e0) - min(e0):.3e} Ha)", flush=True)
        width = max(len(t["excitations_ev"]) for t in ok)
        for j in range(width):
            vals = [t["excitations_ev"][j] for t in ok
                    if len(t["excitations_ev"]) > j]
            cs = {t["root_characters"][j] for t in ok
                  if len(t["root_characters"]) > j}
            flag = "" if len(cs) == 1 else "   <- CHARACTER MOVED"
            print(f"root {j + 1}:     spread {max(vals) - min(vals):.3f} eV"
                  f"  mean {np.mean(vals):.3f}  chars {sorted(cs)}{flag}",
                  flush=True)
        nconv = sum(1 for t in ok if t["converged"])
        print(f"converged:  {nconv}/{len(ok)}", flush=True)

    if args.out:
        with open(args.out, "w") as fh:
            json.dump({"molecule": name, "basis": args.basis,
                       "protocol": args.protocol, "proto": proto,
                       "omp_num_threads": threads, "nroots": nroots,
                       "trials": trials}, fh, indent=2)
        print("", flush=True)
        print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
