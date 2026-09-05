#!/usr/bin/env python3
"""Where a recommendation stops being reproducible, and which stage does it.

Twisted ethylene returns CAS(2e,2o) on most runs and CAS(4e,3o) on some, with
the SCF converged every time, and it is the only molecule in the benchmark that
does this. `docs/BACKLOG.md` attributes it to the APC ranking inheriting a
near-degeneracy from an RHF reference that is qualitatively wrong for a singlet
diradical. That is a hypothesis about a mechanism, and the two spaces differ in
their electron count as well as their orbital count, which means the *pool*
moved. The pool is chosen by the projector, before the ranking runs at all.

So this script does not test the hypothesis. It walks the pipeline stage by
stage and asks which stage is the first to give a different answer on an
identical input, because that is the question a fix has to be built on:

  1. the SCF                -- does `e_tot` reproduce to all digits?
  2. the projector          -- do the eigenvalues reproduce, and is any of them
                               sitting on the 0.2 admission threshold?
  3. the APC ranking        -- do the entropies reproduce?
  4. the recommendation     -- does the published tier reproduce?

Each stage is recorded at full precision and compared across repeats by exact
equality, because "the same to four decimal places" is what hid this in the
first place. A stage that varies while every earlier stage is identical is the
stage that owns the problem.

Thread counts are recorded rather than set: they belong to the environment a
process is created with, and by the time this module is imported numpy has
already made its decision. To test whether reduction order is the mechanism,
run it twice:

    PYTHONPATH=$PWD python3 scripts/casbench/recommend_repro.py --repeats 8
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=$PWD \
        python3 scripts/casbench/recommend_repro.py --repeats 8

If the second is reproducible and the first is not, the mechanism is reduction
order. If both vary, it is not, and the culprit is a genuine near-degeneracy
that a deterministic tie-break has to resolve.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    os.path.dirname(__file__)))))

from scripts.casbench import reference_data as ref          # noqa: E402
from scripts.casbench.run_bench import _mf                  # noqa: E402

# The projector admits an orbital at this eigenvalue. An eigenvalue sitting
# within a whisker of it is a coin toss that no amount of solver tightening
# settles, so the distance to it is reported alongside the values themselves.
THRESHOLD = 0.2


def _threads() -> str:
    got = {v: os.environ.get(v) for v in
           ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}
    return ", ".join(f"{k.split('_')[0].lower()}={v}"
                     for k, v in got.items() if v) or "unset"


def _spread(values) -> float:
    """The widest disagreement between runs, over a vector-valued quantity.

    Vectors of different length between runs mean the pool itself changed
    size, which is not a spread at all; that is reported as infinite so it
    cannot be read as a small number.
    """
    parsed = []
    for v in values:
        try:
            parsed.append([float(x) for x in v.split()])
        except (TypeError, ValueError):
            return float("inf")
    if not parsed:
        return 0.0
    if len({len(p) for p in parsed}) > 1:
        return float("inf")
    arr = np.asarray(parsed, float)
    return float(np.max(np.abs(arr.max(axis=0) - arr.min(axis=0))))


def one_run(name: str, basis: str):
    """Every intermediate the pipeline passes through, at full precision."""
    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.projector import project
    from app.chemistry.cas.ranking import rank_pool
    from app.chemistry.cas.recommend import recommend

    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    mol, mf = _mf(syms, co, basis, chg, mult)

    per_val = perceive(syms, co, include_sigma=False)
    try:
        pool = project(mf, per_val.targets, threshold=THRESHOLD)
    except ValueError:
        pool = None

    out = {
        "scf_energy": repr(float(mf.e_tot)),
        "scf_converged": bool(mf.converged),
    }

    if pool is not None:
        # Sorted so that an ordering difference between runs, which is not a
        # difference in the space, cannot pass for one.
        occ = np.sort(np.asarray(pool.occ_weights, float))
        vir = np.sort(np.asarray(pool.vir_weights, float))
        out["proj_occ_weights"] = " ".join(repr(float(w)) for w in occ)
        out["proj_vir_weights"] = " ".join(repr(float(w)) for w in vir)
        out["proj_space"] = f"({sum(pool.nelecas)}e,{pool.ncas}o)"
        allw = np.hstack([occ, vir])
        near = allw[np.abs(allw - THRESHOLD) < 0.05]
        out["_near_threshold"] = sorted(float(w) for w in near)
        out["_closest_gap"] = (float(np.min(np.abs(allw - THRESHOLD)))
                               if allw.size else None)

        ranked = rank_pool(mf, pool, spin_2s=mult - 1)
        ent = np.asarray(ranked.entropies, float)
        out["apc_entropies"] = " ".join(repr(float(e)) for e in ent)

    rec = recommend(mf, syms, co, spin_2s=mult - 1)
    for tier_name, tier in sorted(rec.tiers.items()):
        out[f"tier_{tier_name}"] = f"({tier.n_electrons}e,{tier.n_orbitals}o)"
    out["recommended_tier"] = rec.recommended
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--molecule", default="ethylene_twisted")
    ap.add_argument("--control", default="ethylene",
                    help="a molecule that is known to reproduce, so that a "
                         "run showing nothing is distinguishable from a "
                         "harness that cannot see anything")
    ap.add_argument("--basis", default="def2-svp")
    ap.add_argument("--repeats", type=int, default=8)
    args = ap.parse_args()

    print(f"[repro] threads: {_threads()}")
    print(f"[repro] basis {args.basis}, {args.repeats} repeats each\n")

    verdicts = {}
    for name in [args.molecule] + ([args.control] if args.control else []):
        print(f"=== {name} ===")
        runs = []
        for i in range(args.repeats):
            try:
                runs.append(one_run(name, args.basis))
            except Exception as exc:                        # noqa: BLE001
                print(f"  run {i + 1}: FAILED {type(exc).__name__}: {exc}")
        if not runs:
            print("  nothing ran\n")
            continue

        # Continuous quantities are reported as a spread and discrete ones as
        # a set of answers, because they fail differently and mixing them
        # hides the finding. Every float in this pipeline moves at the last
        # couple of digits on a threaded machine, so counting distinct values
        # marks all of them as varying and says nothing. What matters is
        # whether that movement is small enough to be reduction-order noise or
        # large enough to be a different solution, and whether it reaches an
        # answer a user sees.
        continuous = ("scf_energy", "proj_occ_weights", "proj_vir_weights",
                      "apc_entropies")
        for key in [k for k in runs[0] if not k.startswith("_")]:
            values = [str(r.get(key)) for r in runs]
            if key in continuous:
                spread = _spread(values)
                verdict = ("identical" if spread == 0.0 else
                           f"spread {spread:.3e}")
                flag = "  <-- NOT NOISE" if spread > 1e-9 else ""
                print(f"  {key:22s} {verdict}{flag}")
                continue
            uniq = sorted(set(values))
            if len(uniq) == 1:
                shown = uniq[0]
                shown = shown if len(shown) <= 60 else shown[:57] + "..."
                print(f"  {key:22s} same           {shown}")
            else:
                print(f"  {key:22s} {len(uniq)} DISTINCT  <-- reaches the user")
                for v in uniq:
                    print(f"      x{values.count(v):<3d} {v}")

        first_varying = next(
            (k for k in runs[0]
             if not k.startswith("_") and k not in continuous
             and len({str(r.get(k)) for r in runs}) > 1), None)

        near = runs[0].get("_near_threshold") or []
        gap = runs[0].get("_closest_gap")
        if gap is not None:
            print(f"  closest projector eigenvalue to the {THRESHOLD} "
                  f"threshold: {gap:.2e} away")
            if near:
                print(f"  eigenvalues within 0.05 of it: "
                      f"{', '.join(f'{w:.6f}' for w in near)}")

        verdicts[name] = first_varying
        answer = first_varying or "none, reproducible"
        print(f"  --> first stage to vary: {answer}\n")

    print("=== verdict ===")
    for name, stage in verdicts.items():
        if stage is None:
            print(f"  {name}: reproducible across {args.repeats} runs")
        else:
            print(f"  {name}: diverges first at '{stage}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
