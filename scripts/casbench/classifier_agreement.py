"""Do the engine's two orbital classifiers agree about the same orbitals?

There are two, they answer the same question by different routes, and a user
meets one or the other depending on which job they ran. Nothing has ever checked
that they agree.

  - `cas.refine.orbital_characters` projects each orbital onto the oriented
    minao targets that perception emits, and reports pi / n / sigma weights
    alongside a label. A `cas_reco` refinement reports this one.
  - `jobs.molden.classify_orbital_character` uses a Mulliken population for the
    atom and, for a planar molecule, the orbital's symmetry under reflection in
    the molecular plane for the shape. The orbital viewer reports this one.

They are not redundant. The projection knows what perception was aiming at and
can say "this is 0.99 lone pair and 0.65 sigma at once"; the reflection test
knows nothing about targets and is exact for a planar molecule, where a'' is pi
and a' is not. So a disagreement is informative in both directions, and the
useful output is not a score but a list of where they part company.

Labels are normalised to pi / n / sigma before comparing, since one set marks
virtuals with a star and the other does not, and the star is a statement about
occupation rather than about shape.

Usage:
    python3 scripts/casbench/classifier_agreement.py
    python3 scripts/casbench/classifier_agreement.py uracil formaldehyde
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from pyscf import gto, scf                                       # noqa: E402

from app.chemistry.cas.geometry import perceive                  # noqa: E402
from app.chemistry.cas.recommend import recommend                # noqa: E402
from app.chemistry.cas.refine import orbital_characters          # noqa: E402
from app.chemistry.jobs.molden import classify_orbital_character  # noqa: E402
from scripts.casbench import reference_data as ref               # noqa: E402

BASIS = os.environ.get("QC_CLS_BASIS", "def2-svp")


def norm(label):
    """pi / n / sigma, dropping the star and the mixed cases."""
    if not label:
        return None
    t = str(label).strip().rstrip("*")
    if t in ("n", "lone_pair"):
        return "n"
    if t.startswith("n/"):          # the engine's honest "both" label
        return "n"
    if t == "pi":
        return "pi"
    if t == "sigma":
        return "sigma"
    return None                     # "mixed", or anything unrecognised


def compare(name):
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    mol = gto.M(atom=atom, basis=BASIS, charge=int(chg), spin=int(mult) - 1,
                verbose=0)
    mf = (scf.RHF(mol) if mult == 1 else scf.ROHF(mol)).density_fit()
    mf.kernel()

    rec = recommend(mf, syms, co, spin_2s=int(mult) - 1)
    tier = rec.tiers[rec.recommended]
    caslst = list(getattr(tier, "orbital_indices", []) or [])
    if not caslst:
        return None
    per = perceive(syms, co, include_sigma=True)
    pi_t = [t for t in per.targets if t.kind == "pi"]
    lp_t = [t for t in per.targets if t.kind == "lone_pair"]
    sg_t = [t for t in per.targets if t.kind == "sigma"]

    block = rec.mo_coeff[:, caslst]
    n_occ = int(np.sum(np.asarray(mf.mo_occ, float) > 0))
    occ = np.array([2.0 if c < n_occ else 0.0 for c in caslst])

    proj, _w = orbital_characters(mol, block, occ, pi_t, lp_t, sg_t)
    mold = classify_orbital_character(mol, block, occ)
    refl = [m.get("character") for m in mold]

    rows = []
    for j, c in enumerate(caslst):
        a, b = norm(proj[j]), norm(refl[j])
        rows.append((c, proj[j], refl[j], a, b,
                     None if (a is None or b is None) else a == b))
    return rows


def main(names):
    print(f"# Do the two orbital classifiers agree? {BASIS}, recommended tier")
    print("")
    print("Projection is `cas.refine.orbital_characters`; reflection is "
          "`jobs.molden.classify_orbital_character`.")
    print("")
    print("| molecule | mo | projection | reflection | agree |")
    print("|---|---|---|---|---|")
    agree = disagree = undecided = 0
    detail = []
    for name in names:
        try:
            rows = compare(name)
        except Exception as exc:                                 # noqa: BLE001
            print(f"| {name} | | | | failed: {type(exc).__name__} |")
            continue
        if not rows:
            continue
        for c, p, r, a, b, ok in rows:
            if ok is None:
                undecided += 1
                mark = "not comparable"
            elif ok:
                agree += 1
                mark = "yes"
            else:
                disagree += 1
                mark = "**NO**"
                detail.append((name, c, p, r))
            print(f"| {name} | {c} | {p} | {r} | {mark} |")
        sys.stdout.flush()

    total = agree + disagree
    print("")
    if total:
        print(f"Agreed on {agree} of {total} comparable orbitals "
              f"({100.0 * agree / total:.0f}%), with {undecided} not comparable "
              f"because one side said `mixed` or had no opinion.")
    if detail:
        print("")
        print("Where they part company:")
        for name, c, p, r in detail:
            print(f"  - {name} mo {c}: projection says {p}, reflection says {r}")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args or list(ref.REFERENCE_SPACES.keys()))
