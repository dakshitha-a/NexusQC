"""How much of a predicted state's hole does the recommended space actually hold?

Every count in section 10.1 is a count of orbitals. A space can match the
literature size exactly and still be unable to describe the state it was sized
for, and uracil is the case that proves it: the narrowed (14e,10o) is the right
size, holds two orbitals the classifier calls `n`, and a singlet-constrained
CASCI in it produces no n->pi* root at any root count, because those two columns
carry only 38% of the hole the state excites out of. Everything downstream
follows from that one number. The n->pi* configurations built on a 38% hole land
near 16 eV instead of near 5, the state average never contains the state, and
the orbital optimisation cannot repair it either: both columns sit at occupation
2.000 in every averaged root, and the rotation between two doubly occupied
orbitals has no gradient to follow.

So this measures the thing the orbital count cannot see. For each predicted
state it takes the hole natural transition orbital from the linear-response
pass, projects it onto the space the engine recommends, and reports the fraction
captured. A state whose hole is spanned is reachable in the space; one whose
hole is not spanned is not reachable at any root count, and no amount of
augmenting or reseeding recovers it.

Two controls come with it, because the number is only meaningful if neither
confounds it:

  - the hole is a Kohn-Sham orbital and the space is built from RHF columns, so
    the KS hole's projection onto the whole RHF occupied space is reported
    first. Anything below about 0.98 there means the two orbital sets differ
    enough to be the story, rather than the selection
  - whether the recommendation's columns are canonical SCF orbitals or the
    projector's rotated ones is reported once, since it decides where a fix
    would have to go

Usage:
    python3 scripts/casbench/hole_capture.py                 # every molecule
    python3 scripts/casbench/hole_capture.py uracil formaldehyde
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from pyscf import dft, gto, scf, tdscf                           # noqa: E402

from app.chemistry.cas.excited import analyse                    # noqa: E402
from app.chemistry.cas.geometry import perceive                  # noqa: E402
from app.chemistry.cas.narrow import narrow_to_states            # noqa: E402
from app.chemistry.cas.recommend import recommend                # noqa: E402
from app.chemistry.cas.refine import orbital_characters          # noqa: E402
from scripts.casbench import reference_data as ref               # noqa: E402

BASIS = os.environ.get("QC_HOLE_BASIS", "def2-svpd")
N_STATES = 3
# Below this the space cannot describe the state, whatever its size says.
SPANNED = 0.80


def _mol(name, basis):
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    mol = gto.M(atom=atom, basis=basis, charge=int(chg),
                spin=int(mult) - 1, verbose=0)
    return mol, syms, co, int(mult) - 1


def capture(name):
    mol, syms, co, spin = _mol(name, BASIS)
    if spin:
        mf = scf.ROHF(mol).density_fit()
    else:
        mf = scf.RHF(mol).density_fit()
    mf.kernel()

    rec = recommend(mf, syms, co, spin_2s=spin, n_states=N_STATES)
    per = perceive(syms, co, include_sigma=True)
    pi_t = [t for t in per.targets if t.kind == "pi"]
    lp_t = [t for t in per.targets if t.kind == "lone_pair"]
    sg_t = [t for t in per.targets if t.kind == "sigma"]

    ks = dft.RKS(mol) if not spin else dft.ROKS(mol)
    ks.xc = "camb3lyp"
    ks = ks.density_fit()
    ks.kernel()
    td = tdscf.TDA(ks)
    td.nstates = max(6, N_STATES + 3)
    td.kernel()
    an = analyse(ks, td, per.targets, n_states=N_STATES)

    try:
        caslst, nelec = narrow_to_states(mol, rec, rec.tiers[rec.recommended],
                                         an, N_STATES, pi_t, lp_t, nroots=6,
                                         csf_budget=float("inf"),
                                         perception=per)
    except Exception:                                            # noqa: BLE001
        tier = rec.tiers[rec.recommended]
        caslst = list(getattr(tier, "orbital_indices", []) or [])
        nelec = tier.n_electrons
    if not caslst:
        return None

    s1e = mol.intor("int1e_ovlp")
    act = rec.mo_coeff[:, caslst]
    sa = act.T @ s1e @ act
    w, v = np.linalg.eigh(sa)
    keep = w > 1e-10
    act_o = act @ (v[:, keep] / np.sqrt(w[keep]))

    # Is the recommendation handing back canonical SCF columns, or rotated ones?
    ov_can = np.abs(rec.mo_coeff.T @ s1e @ np.asarray(mf.mo_coeff))
    diag = float(np.mean(np.diag(ov_can)[:len(caslst) + 8]))
    rotated = diag < 0.99

    occ_idx = np.where(np.asarray(ks.mo_occ, float) > 0)[0]
    vir_idx = np.where(np.asarray(ks.mo_occ, float) == 0)[0]
    rhf_occ = np.asarray(mf.mo_coeff)[:, np.asarray(mf.mo_occ, float) > 0]

    n_occ_all = len(caslst)
    labels, _w = orbital_characters(mol, act, np.zeros(n_occ_all),
                                    pi_t, lp_t, sg_t)

    rows = []
    for i, st in enumerate(an.states[:N_STATES]):
        if i >= len(td.xy):
            break
        x = np.asarray(td.xy[i][0])
        u, _s, vt = np.linalg.svd(x)
        hole = ks.mo_coeff[:, occ_idx] @ u[:, 0]
        part = ks.mo_coeff[:, vir_idx] @ vt[0, :]
        hole = hole / np.sqrt(float(hole.T @ s1e @ hole))
        part = part / np.sqrt(float(part.T @ s1e @ part))
        # Control: does the KS hole live in the RHF occupied space at all?
        in_rhf = float(np.sum((rhf_occ.T @ s1e @ hole) ** 2))
        ph = float(np.sum((act_o.T @ s1e @ hole) ** 2))
        pp = float(np.sum((act_o.T @ s1e @ part) ** 2))
        rows.append((st.character, float(st.energy_ev), ph, pp, in_rhf))
    return {"space": (nelec, len(caslst)), "rotated": rotated,
            "labels": labels, "rows": rows}


def main(names):
    print(f"# Hole capture in the recommended space, {BASIS}, "
          f"{N_STATES} states requested")
    print("")
    print("| molecule | space | columns | state | eV | hole in space | "
          "particle | hole in RHF occ | verdict |")
    print("|---|---|---|---|---|---|---|---|---|")
    short = []
    for name in names:
        try:
            r = capture(name)
        except Exception as exc:                                 # noqa: BLE001
            print(f"| {name} | | | | | | | | failed: {type(exc).__name__} |")
            continue
        if r is None:
            continue
        ne, no = r["space"]
        for char, ev, ph, pp, in_rhf in r["rows"]:
            ok = "spanned" if ph >= SPANNED else "**NOT SPANNED**"
            if ph < SPANNED:
                short.append((name, char, ph))
            col = "rotated" if r["rotated"] else "canonical"
            print(f"| {name} | ({ne}e,{no}o) | {col} | {char} | {ev:.2f} | "
                  f"{ph:.3f} | {pp:.3f} | {in_rhf:.3f} | {ok} |")
        sys.stdout.flush()
    print("")
    print(f"States whose hole the recommended space does not span "
          f"(below {SPANNED}): {len(short)}")
    for name, char, ph in short:
        print(f"  - {name}: {char} at {ph:.3f}")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args or list(ref.REFERENCE_SPACES.keys()))
