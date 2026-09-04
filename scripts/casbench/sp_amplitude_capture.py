"""Can the lone-pair target's s amplitude recover the missing hole?

P4.0 swept LONE_PAIR_S_AMPLITUDE and found the literature match flat at 11/17 across
0.35 to 0.85, concluding the constant is not delicate. That conclusion was drawn
against a count of orbitals, which is exactly the metric that cannot see whether
the space holds the state. Re-run the same sweep against hole capture.

The question this answers is the scope question. If capture peaks well away from
the 0.577 in use, the fix is a constant and it is contained. If it is flat and
low everywhere, no choice of atomic target recovers the hole and the active
lone-pair columns really do have to be rotated onto the state, which is the
larger change.

The linear-response pass does not depend on the amplitude, so it runs once per
molecule and every amplitude reuses it.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from pyscf import dft, gto, scf, tdscf                           # noqa: E402

from app.chemistry.cas import geometry                           # noqa: E402
from app.chemistry.cas.excited import analyse                    # noqa: E402
from app.chemistry.cas.narrow import narrow_to_states            # noqa: E402
from app.chemistry.cas.recommend import recommend                # noqa: E402
from scripts.casbench import reference_data as ref               # noqa: E402

BASIS = "def2-svpd"
AMPS = [float(a) for a in os.environ["QC_CAP_AMPS"].split(",")] \
    if os.environ.get("QC_CAP_AMPS") else \
    [0.0, 0.2, 0.35, 0.5, 0.577, 0.65, 0.75, 0.85, 0.95]
MOLS = sys.argv[1:] or ["formaldehyde", "acetone", "acrolein", "uracil"]


def prep(name):
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    mol = gto.M(atom=atom, basis=BASIS, verbose=0)
    mf = scf.RHF(mol).density_fit()
    mf.kernel()
    ks = dft.RKS(mol)
    ks.xc = "camb3lyp"
    ks = ks.density_fit()
    ks.kernel()
    td = tdscf.TDA(ks)
    td.nstates = 6
    td.kernel()
    return mol, syms, co, mf, ks, td


def holes(mol, ks, td, an, s1e):
    """The hole NTO of each predicted n->* state, normalised."""
    occ_idx = np.where(np.asarray(ks.mo_occ, float) > 0)[0]
    out = []
    for i, st in enumerate(an.states[:3]):
        if i >= len(td.xy) or not st.character.startswith("n->"):
            continue
        x = np.asarray(td.xy[i][0])
        u, _s, _vt = np.linalg.svd(x)
        h = ks.mo_coeff[:, occ_idx] @ u[:, 0]
        out.append((st.character, float(st.energy_ev),
                    h / np.sqrt(float(h.T @ s1e @ h))))
    return out


print(f"# Lone-pair s amplitude against hole capture, {BASIS}")
print("")
print("| molecule | state | " + " | ".join(f"{a:.3f}" for a in AMPS) + " |")
print("|---" * (len(AMPS) + 2) + "|")

for name in MOLS:
    try:
        mol, syms, co, mf, ks, td = prep(name)
    except Exception as exc:                                     # noqa: BLE001
        print(f"| {name} | failed: {type(exc).__name__} |")
        continue
    s1e = mol.intor("int1e_ovlp")
    rows = {}
    ref_holes = None
    for amp in AMPS:
        geometry.LONE_PAIR_S_AMPLITUDE = amp
        per = geometry.perceive(syms, co, include_sigma=True)
        pi_t = [t for t in per.targets if t.kind == "pi"]
        lp_t = [t for t in per.targets if t.kind == "lone_pair"]
        rec = recommend(mf, syms, co, spin_2s=0, n_states=3)
        an = analyse(ks, td, per.targets, n_states=3)
        if ref_holes is None:
            ref_holes = holes(mol, ks, td, an, s1e)
        try:
            caslst, _ne = narrow_to_states(mol, rec, rec.tiers[rec.recommended],
                                           an, 3, pi_t, lp_t, nroots=6,
                                           csf_budget=float("inf"),
                                           perception=per)
        except Exception:                                        # noqa: BLE001
            caslst = list(getattr(rec.tiers[rec.recommended],
                                  "orbital_indices", []) or [])
        act = rec.mo_coeff[:, caslst]
        sa = act.T @ s1e @ act
        w, v = np.linalg.eigh(sa)
        keep = w > 1e-10
        act_o = act @ (v[:, keep] / np.sqrt(w[keep]))
        for char, ev, h in ref_holes:
            key = f"{char} {ev:.2f}"
            rows.setdefault(key, []).append(
                float(np.sum((act_o.T @ s1e @ h) ** 2)))
    for key, vals in rows.items():
        best = max(vals)
        mark = "" if best < 0.80 else "  <-- reaches 0.80"
        print(f"| {name} | {key} | "
              + " | ".join(f"{v:.3f}" for v in vals) + f" |{mark}")
    sys.stdout.flush()

geometry.LONE_PAIR_S_AMPLITUDE = 1.0 / np.sqrt(3.0)
