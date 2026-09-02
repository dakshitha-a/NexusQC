#!/usr/bin/env python3
"""Benchmark the CAS recommendation engine against the literature and legacy.

Runs in process, not through JobManager: faster, and it creates no jobs or
conversations that would then need tracking and purging.

    python3 scripts/casbench/run_bench.py --set spaces
    python3 scripts/casbench/run_bench.py --set stability
    python3 scripts/casbench/run_bench.py --set excited
    python3 scripts/casbench/run_bench.py --set nevpt2
    python3 scripts/casbench/run_bench.py --set all --out results.json

The four sets answer four different questions.

**spaces**    Does the recommendation match the active space the
              multireference literature uses for this molecule?
**stability** Is it the same space across basis sets and under random
              rotations of the input geometry? This is the property the legacy
              path does not have, so legacy is run alongside for contrast.
**excited**   Are the requested states found, with the right character, and how
              close are their energies to the QUEST best estimates?
**nevpt2**    The end-to-end number: SA-CASSCF in the recommended space
              followed by strongly contracted NEVPT2, against the same best
              estimates. This is what a user actually gets.

Legacy comparison is by (ne,no) and by stability. The legacy runner refuses
open-shell molecules and caps at twelve orbitals, so on part of this set it has
no answer at all, which is itself a result and is reported as one.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.casbench import reference_data as ref   # noqa: E402

BASES = ["sto-3g", "cc-pvdz", "def2-svp", "def2-tzvp", "aug-cc-pvdz"]
HARTREE_TO_EV = 27.211386245988


def _geom(syms, co):
    return "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}" for s, c in zip(syms, co))


def _mf(syms, co, basis, charge, mult, dft_xc=None):
    from pyscf import dft, gto, scf
    mol = gto.M(atom=_geom(syms, co), basis=basis, charge=charge,
                spin=mult - 1, verbose=0)
    if dft_xc:
        m = dft.RKS(mol) if mult == 1 else dft.ROKS(mol)
        m.xc = dft_xc
    else:
        m = scf.RHF(mol) if mult == 1 else scf.ROHF(mol)
    m = m.density_fit()
    m.kernel()
    return mol, m


def _rot(rng):
    A = rng.standard_normal((3, 3))
    Q, R = np.linalg.qr(A)
    Q *= np.sign(np.diag(R))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q


def recommend_new(name, basis="def2-svp", coords=None):
    from app.chemistry.cas.recommend import recommend
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(coords if coords is not None else co, float)
    t0 = time.time()
    mol, mf = _mf(syms, co, basis, chg, mult)
    rec = recommend(mf, syms, co, spin_2s=mult - 1)
    return rec, time.time() - t0, mol, mf


def recommend_legacy(name, basis="def2-svp", coords=None, max_orb=12):
    """The legacy AVAS pilot, for contrast.

    Calls the legacy helpers directly rather than the whole runner, because the
    runner ends in a full state-averaged CASSCF and what is being compared here
    is the *space it chooses*, not the CASSCF that follows.
    """
    from scripts.casbench.legacy_cas_reco import _avas_pilot_space, _truncate_avas_space
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(coords if coords is not None else co, float)
    if mult != 1:
        return None, 0.0, "refuses open-shell molecules"
    t0 = time.time()
    try:
        mol, mf = _mf(syms, co, basis, chg, mult)
        ncas, nelec, mo, _labels, _notes = _avas_pilot_space(mf, mol, {}, "[bench]")
        mo, ncas, nelec, _trunc, _note = _truncate_avas_space(
            mol, mo, ncas, nelec, max_orb, "[bench]")
        total = nelec if isinstance(nelec, int) else sum(nelec)
        return (total, ncas), time.time() - t0, None
    except Exception as exc:                                   # noqa: BLE001
        return None, time.time() - t0, f"{type(exc).__name__}: {exc}"


def set_spaces():
    """Recommended space vs the space the literature uses."""
    rows = []
    for name in sorted(ref.REFERENCE_SPACES):
        if name not in ref.GEOMETRIES:
            continue
        expected, desc, src = ref.REFERENCE_SPACES[name]
        rec, dt, _mol, _mf = recommend_new(name)
        got = rec.space
        tiers = {k: (t.n_electrons, t.n_orbitals) for k, t in rec.tiers.items()}
        match = "exact" if got == expected else (
            "tier" if expected in tiers.values() else "differs")
        leg, ldt, lerr = recommend_legacy(name)
        rows.append({
            "molecule": name, "reference": list(expected), "reference_note": desc,
            "reference_source": src, "recommended": list(got),
            "tiers": {k: list(v) for k, v in tiers.items()},
            "match": match, "seconds": round(dt, 2),
            "legacy": list(leg) if leg else None,
            "legacy_seconds": round(ldt, 2), "legacy_error": lerr,
        })
        star = {"exact": "==", "tier": "~=", "differs": "!="}[match]
        legs = f"{tuple(leg)}" if leg else f"({lerr})"
        print(f"  {name:16s} ref {str(expected):8s} {star} new {str(got):8s} "
              f"[min {tiers['minimal']} max {tiers['maximal']}]  "
              f"{dt:5.1f}s   legacy {legs}")
    n_ok = sum(1 for r in rows if r["match"] in ("exact", "tier"))
    print(f"\n  {n_ok}/{len(rows)} molecules matched the literature space "
          f"exactly or as one of the offered tiers")
    return rows


def set_stability():
    """Same space across basis sets and under rotation? Legacy alongside."""
    rng = np.random.default_rng(20260902)
    rows = []
    for name in sorted(ref.REFERENCE_SPACES):
        if name not in ref.GEOMETRIES:
            continue
        syms, co, chg, mult = ref.molecule(name)
        co = np.asarray(co, float)

        new_by_basis, leg_by_basis = {}, {}
        for b in BASES:
            try:
                rec, _dt, _m, _mfo = recommend_new(name, basis=b)
                new_by_basis[b] = rec.space
            except Exception as exc:                            # noqa: BLE001
                new_by_basis[b] = f"ERR {type(exc).__name__}"
            leg, _ldt, lerr = recommend_legacy(name, basis=b)
            leg_by_basis[b] = leg if leg else f"ERR {lerr}"

        new_rot, leg_rot = set(), set()
        for _ in range(5):
            R = _rot(rng)
            c2 = co @ R.T
            try:
                rec, _dt, _m, _mfo = recommend_new(name, basis="def2-svp", coords=c2)
                new_rot.add(rec.space)
            except Exception as exc:                            # noqa: BLE001
                new_rot.add(f"ERR {type(exc).__name__}")
            leg, _ldt, lerr = recommend_legacy(name, basis="def2-svp", coords=c2)
            leg_rot.add(leg if leg else f"ERR {lerr}")

        n_basis = len({str(v) for v in new_by_basis.values()})
        l_basis = len({str(v) for v in leg_by_basis.values()})
        rows.append({
            "molecule": name,
            "new_by_basis": {k: list(v) if isinstance(v, tuple) else v
                             for k, v in new_by_basis.items()},
            "legacy_by_basis": {k: list(v) if isinstance(v, tuple) else v
                                for k, v in leg_by_basis.items()},
            "new_distinct_over_bases": n_basis,
            "legacy_distinct_over_bases": l_basis,
            "new_distinct_over_rotations": len(new_rot),
            "legacy_distinct_over_rotations": len(leg_rot),
        })
        print(f"  {name:16s} new: {n_basis} distinct over {len(BASES)} bases, "
              f"{len(new_rot)} over 5 rotations   |   "
              f"legacy: {l_basis} over bases, {len(leg_rot)} over rotations")
    tot_new_b = sum(r["new_distinct_over_bases"] > 1 for r in rows)
    tot_leg_b = sum(r["legacy_distinct_over_bases"] > 1 for r in rows)
    tot_new_r = sum(r["new_distinct_over_rotations"] > 1 for r in rows)
    tot_leg_r = sum(r["legacy_distinct_over_rotations"] > 1 for r in rows)
    print(f"\n  molecules whose space CHANGES with the basis:  new {tot_new_b}, "
          f"legacy {tot_leg_b}  (of {len(rows)})")
    print(f"  molecules whose space CHANGES under rotation:  new {tot_new_r}, "
          f"legacy {tot_leg_r}  (of {len(rows)})")
    return rows


def set_excited(basis="aug-cc-pvdz", nstates=10):
    """Are the states found, with the right character and energy?"""
    from pyscf import tdscf

    from app.chemistry.cas.excited import analyse
    from app.chemistry.cas.geometry import perceive

    rows = []
    for name in sorted(ref.EXCITATIONS):
        if name not in ref.GEOMETRIES:
            continue
        syms, co, chg, mult = ref.molecule(name)
        co = np.asarray(co, float)
        t0 = time.time()
        try:
            mol, mf = _mf(syms, co, basis, chg, mult, dft_xc="camb3lyp")
            td = tdscf.TDA(mf)
            td.nstates = nstates
            td.kernel()
            per = perceive(syms, co, include_sigma=False)
            an = analyse(mf, td, per.targets, n_states=nstates // 2)
        except Exception as exc:                                # noqa: BLE001
            print(f"  {name:16s} FAILED {type(exc).__name__}: {exc}")
            rows.append({"molecule": name, "error": str(exc)})
            continue
        dt = time.time() - t0

        matched = []
        for label, character, tbe, src in ref.EXCITATIONS[name]:
            want_ryd = "Rydberg" in character
            want_kind = character.split("->")[0].strip()
            best, best_err = None, 1e9
            for s in an.states:
                is_ryd = s.particle_kind == "Rydberg"
                if is_ryd != want_ryd:
                    continue
                if want_kind in ("n", "pi") and s.hole_kind not in (want_kind, "mixed"):
                    continue
                err = abs(s.energy_ev - tbe)
                if err < best_err:
                    best, best_err = s, err
            matched.append({
                "label": label, "character": character, "tbe_ev": tbe,
                "source": src,
                "found": best.to_dict() if best else None,
                "error_ev": round(best_err, 3) if best else None,
            })
            got = (f"{best.energy_ev:6.2f} eV {best.character:14s} "
                   f"{'bright' if best.bright else 'dark'}" if best else "NOT FOUND")
            print(f"  {name:16s} {label:8s} {character:24s} TBE {tbe:5.2f}  ->  {got}"
                  + (f"   err {best_err:.2f}" if best else ""))
        rows.append({"molecule": name, "basis": basis, "seconds": round(dt, 1),
                     "diffuse": an.diffuse_present, "matches": matched,
                     "states": [s.to_dict() for s in an.states]})

    errs = [m["error_ev"] for r in rows for m in r.get("matches", [])
            if m.get("error_ev") is not None]
    found = sum(1 for r in rows for m in r.get("matches", []) if m.get("found"))
    total = sum(len(r.get("matches", [])) for r in rows)
    if errs:
        print(f"\n  TDA/CAM-B3LYP vs QUEST best estimates: "
              f"MAE {np.mean(errs):.2f} eV, max {np.max(errs):.2f} eV, "
              f"{found}/{total} reference states located")
    return rows


def _root_characters(mc, mol, targets, nroots):
    """Classify each SA-CASSCF root by the character of its transition from S0.

    Reference states must be matched to computed roots by *character*, not by
    index. Matching by index silently assumes the reference states are the
    lowest few roots of the calculation, and they are not: formaldehyde's
    pi->pi* lies at 9.22 eV, far above root 2 of a state average over three
    roots, so an index match compares it against an n->pi* root and reports a
    5 eV "error" that says nothing about the active space.

    The one-particle transition density matrix between root 0 and root k is
    taken from the CI solver, transformed to the AO basis, and put through the
    same natural-transition-orbital decomposition and target projection the
    excited-state branch uses. So "is this root pi->pi*" is answered by exactly
    the machinery that answers it for the TDA states.
    """
    import numpy as _np

    from app.chemistry.cas.excited import _label, _second_moments, _target_weights

    mo_act = mc.mo_coeff[:, mc.ncore:mc.ncore + mc.ncas]
    occ_mo = mc.mo_coeff[:, :mc.ncore + mc.ncas]
    r2_occ = _second_moments(mol, occ_mo)
    valence_extent = float(_np.max(r2_occ)) if r2_occ.size else 1.0

    out = []
    for k in range(1, nroots):
        try:
            # pyscf's trans_rdm1(bra, ket) returns <bra| q^dagger p |ket>, so
            # the SECOND index runs over the orbital the electron came from and
            # the first over where it went. Reading them the other way round
            # labels formaldehyde's n->pi* state as "pi->n*" -- the transition
            # is right, the two halves are swapped.
            tdm = mc.fcisolver.trans_rdm1(mc.ci[0], mc.ci[k], mc.ncas, mc.nelecas)
            u, sv, vt = _np.linalg.svd(_np.asarray(tdm))
            particle = mo_act @ u[:, 0]
            hole = mo_act @ vt[0, :]
            r2p = float(_second_moments(mol, particle[:, None])[0])
            ratio = r2p / valence_extent if valence_extent else float("nan")
            hk = _label(_target_weights(mol, hole, targets), 0.0, False, True)
            pk = _label(_target_weights(mol, particle, targets), ratio, True, True)
            out.append(f"{hk}->{pk}")
        except Exception:                                       # noqa: BLE001
            out.append("unassigned")
    return out


def set_nevpt2(basis="cc-pvdz", max_csf=200000, extra_roots=3):
    """End to end: SA-CASSCF in the recommended space, then SC-NEVPT2."""
    from pyscf import mcscf, mrpt

    rows = []
    for name in sorted(ref.EXCITATIONS):
        if name not in ref.GEOMETRIES:
            continue
        syms, co, chg, mult = ref.molecule(name)
        if mult != 1:
            continue
        co = np.asarray(co, float)
        refs = ref.EXCITATIONS[name]
        # Valence states only: a Rydberg state is not describable in a valence
        # active space, by construction, and the engine says so rather than
        # pretending otherwise.
        valence = [r for r in refs if "Rydberg" not in r[2 - 1]]
        if not valence:
            continue
        # Extra roots so the reference states have somewhere to be found. A
        # state average over exactly len(valence)+1 roots assumes the reference
        # states are the lowest ones, which is false whenever a molecule has
        # several low n->pi* states below its bright pi->pi*.
        nroots = len(valence) + 1 + extra_roots

        try:
            rec, dt, mol, mf = recommend_new(name, basis=basis)
            ne, no = rec.space
            from app.chemistry.cas import feasibility
            f = feasibility.assess(no, ne)
            if f.n_csf > max_csf:
                print(f"  {name:16s} CAS({ne},{no}) is {f.n_csf:,} CSFs, over the "
                      f"benchmark cap -- skipped, not failed")
                rows.append({"molecule": name, "skipped": "too large",
                             "space": [ne, no], "n_csf": f.n_csf})
                continue
            # A state average cannot ask for more roots than the space has
            # states. CAS(2,2) holds three singlet CSFs, so ethylene's SA-6
            # died inside the FCI solver with an unhelpful broadcast error.
            nroots = min(nroots, f.n_csf)
            t0 = time.time()
            mc = mcscf.CASSCF(mf, no, ne)
            mc.fcisolver.nroots = nroots
            mc.state_average_([1.0 / nroots] * nroots)
            mc.max_cycle_macro = 100
            mc.kernel(rec.mo_coeff)
            e_cas = np.asarray(mc.e_states)

            ci = mcscf.CASCI(mf, no, ne)
            ci.fcisolver.nroots = nroots
            ci.kernel(mc.mo_coeff)
            e_pt = []
            for root in range(nroots):
                e_pt.append(ci.e_tot[root]
                            + mrpt.NEVPT(ci, root=root).kernel())
            e_pt = np.asarray(e_pt)
            dt_cas = time.time() - t0
        except Exception as exc:                                # noqa: BLE001
            print(f"  {name:16s} FAILED {type(exc).__name__}: {str(exc)[:90]}")
            rows.append({"molecule": name, "error": f"{type(exc).__name__}: {exc}"})
            continue

        cas_ev = (e_cas - e_cas[0]) * HARTREE_TO_EV
        pt_ev = (e_pt - e_pt[0]) * HARTREE_TO_EV

        from app.chemistry.cas.geometry import perceive
        targets = perceive(syms, co, include_sigma=False).targets
        chars = _root_characters(mc, mol, targets, nroots)

        entry = {"molecule": name, "space": [ne, no], "basis": basis,
                 "n_roots": nroots, "converged": bool(mc.converged),
                 "seconds": round(dt_cas, 1),
                 "root_characters": chars, "states": []}
        print(f"  {name:16s} CAS({ne},{no}) SA-{nroots}  converged={mc.converged}  "
              f"{dt_cas:5.1f}s   roots: "
              + ", ".join(f"{pt_ev[k+1]:.2f} {chars[k]}" for k in range(len(chars))))

        used = set()
        for label, character, tbe, src in valence:
            want = character.split()[0]
            # Among the roots whose character matches the reference, take the
            # one closest in energy; fall back to the closest root of any
            # character, and record which happened.
            cands = [k for k, c in enumerate(chars, start=1)
                     if c == want and k not in used]
            how = "character"
            if not cands:
                cands = [k for k in range(1, len(pt_ev)) if k not in used]
                how = "energy only (no root carried the reference character)"
            if not cands:
                continue
            k = min(cands, key=lambda kk: abs(pt_ev[kk] - tbe))
            used.add(k)
            entry["states"].append({
                "label": label, "character": character, "tbe_ev": tbe,
                "source": src, "root": k, "root_character": chars[k - 1],
                "matched_by": how,
                "casscf_ev": round(float(cas_ev[k]), 3),
                "nevpt2_ev": round(float(pt_ev[k]), 3),
                "casscf_error": round(float(cas_ev[k] - tbe), 3),
                "nevpt2_error": round(float(pt_ev[k] - tbe), 3),
            })
            print(f"      {label:8s} {character:22s} TBE {tbe:5.2f}   "
                  f"CASSCF {cas_ev[k]:5.2f} ({cas_ev[k]-tbe:+.2f})   "
                  f"NEVPT2 {pt_ev[k]:5.2f} ({pt_ev[k]-tbe:+.2f})   "
                  f"root {k} [{how}]")
        rows.append(entry)

    states = [s for r in rows for s in r.get("states", [])]
    cas_err = [abs(s["casscf_error"]) for s in states]
    pt_err = [abs(s["nevpt2_error"]) for s in states]
    if not pt_err:
        return rows

    print(f"\n  SA-CASSCF MAE {np.mean(cas_err):.2f} eV over {len(cas_err)} states")
    print(f"  SC-NEVPT2 MAE {np.mean(pt_err):.2f} eV over {len(pt_err)} states")

    # Split by character. The aggregate hides the finding: a valence active
    # space describes n->pi* excitations well and *ionic* pi->pi* excitations
    # badly, and the second is a known limitation of the space's size and of
    # the basis, not of how the space was chosen. Reporting one number for both
    # would attribute a physics limitation to the selection method.
    print("\n  by excitation character:")
    for kind, pick in (("n->pi*", lambda c: c.startswith("n->")),
                       ("pi->pi*", lambda c: c.startswith("pi->"))):
        sub = [s for s in states if pick(s["character"])]
        if not sub:
            continue
        e_cas = [abs(s["casscf_error"]) for s in sub]
        e_pt = [abs(s["nevpt2_error"]) for s in sub]
        signed = np.mean([s["nevpt2_error"] for s in sub])
        print(f"    {kind:9s} n={len(sub):2d}   SA-CASSCF MAE {np.mean(e_cas):.2f}   "
              f"SC-NEVPT2 MAE {np.mean(e_pt):.2f}   mean signed error "
              f"{signed:+.2f} eV")

    worst = sorted(states, key=lambda s: -abs(s["nevpt2_error"]))[:3]
    print("\n  largest deviations:")
    for s in worst:
        print(f"    {s['label']:8s} {s['character']:24s} "
              f"NEVPT2 error {s['nevpt2_error']:+.2f} eV")
    print(f"\n  literature bar: {ref.LITERATURE_BAR['scheme']} "
          f"{ref.LITERATURE_BAR['mae_ev']} eV "
          f"({ref.LITERATURE_BAR['n_molecules']} molecules, "
          f"{ref.LITERATURE_BAR['basis']}) -- not like for like: a different "
          f"molecule set, a larger basis and a different downstream")
    return rows


SETS = {"spaces": set_spaces, "stability": set_stability,
        "excited": set_excited, "nevpt2": set_nevpt2}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", default="spaces",
                    choices=list(SETS) + ["all"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    names = list(SETS) if args.set == "all" else [args.set]
    out = {}
    for n in names:
        print(f"\n=== {n} " + "=" * (60 - len(n)))
        t0 = time.time()
        out[n] = SETS[n]()
        print(f"  [{n} took {time.time() - t0:.0f}s]")

    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, default=str))
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
