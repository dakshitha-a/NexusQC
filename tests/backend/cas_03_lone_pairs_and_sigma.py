#!/usr/bin/env python3
"""A hydride gets a pool with virtual orbitals in it, not a full one.

This is the defect a design review caught before any of the engine was
written, and it is subtle enough to be worth stating in full.

The projector's headline targets are pi normals and lone pairs, which is what
a conjugated organic molecule's active space is made of. **Water has neither
a pi system nor a useful pi normal.** A projector emitting only those two
kinds hands water a pool consisting of its oxygen lone pairs and nothing else:
every orbital doubly occupied, no virtual partner, exactly one configuration,
and therefore no correlation described at all. This script measures that
directly -- pi+lone-pair targets alone give water ``(4e, 2o)``, which is full.

That is the same degenerate-pool failure the legacy AVAS runner met from the
other direction, where an ``['O 2p']`` seed on water returned ``(6e, 3o)``;
it grew a hydrogen-reseed rule and then a terminal error guard to cope
(``casreco_02_avas_seed_and_guard.py``). Emitting **sigma-bond targets** --
one on each end of every bond, so the bonding and antibonding combinations are
both reachable -- fixes it at the source rather than special-casing hydrides:
water becomes ``(8e, 6o)``, with virtuals, in every basis.

The general rule this locks down: a pool in which every orbital is doubly
occupied is never a valid recommendation, whatever molecule produced it.

Needs pyscf but no live stack. Small RHF calculations only, no CASSCF.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_03_lone_pairs_and_sigma.py
"""
import numpy as np
from pyscf import gto, scf

from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.projector import project

PASS = 0
FAIL = 0

BASES = ["sto-3g", "cc-pvdz", "def2-tzvp"]

WATER = (["O", "H", "H"],
         np.asarray([[0, 0, 0.117], [0, 0.757, -0.469], [0, -0.757, -0.469]], float))
AMMONIA = (["N", "H", "H", "H"],
           np.asarray([[0, 0, 0.1173], [0, 0.9377, -0.2737], [0.8121, -0.4689, -0.2737],
                       [-0.8121, -0.4689, -0.2737]], float))
METHANE = (["C", "H", "H", "H", "H"],
           np.asarray([[0, 0, 0], [0.6276, 0.6276, 0.6276], [-0.6276, -0.6276, 0.6276],
                       [-0.6276, 0.6276, -0.6276], [0.6276, -0.6276, -0.6276]], float))
CH2O = (["C", "O", "H", "H"],
        np.asarray([[0, 0, -0.5295], [0, 0, 0.6755], [0, 0.94, -1.10],
                    [0, -0.94, -1.10]], float))


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def _geom(syms, co):
    return "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}" for s, c in zip(syms, co))


def _pool(syms, co, basis, include_sigma):
    mol = gto.M(atom=_geom(syms, co), basis=basis, verbose=0)
    mf = scf.RHF(mol).density_fit().run()
    per = perceive(syms, co, include_sigma=include_sigma)
    return project(mf, per.targets)


def _rot(rng):
    A = rng.standard_normal((3, 3))
    Q, R = np.linalg.qr(A)
    Q *= np.sign(np.diag(R))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q


def main() -> int:
    print("Without sigma targets, water's pool is completely full -- the "
          "failure this branch exists to prevent")
    ps = _pool(*WATER, "cc-pvdz", include_sigma=False)
    ne, no = sum(ps.nelecas), ps.ncas
    check(f"water, pi+lone-pair targets only: CAS({ne},{no}) is full "
          f"({ne} electrons in {no} orbitals)",
          ne == 2 * no, f"got CAS({ne},{no}); expected a full pool")
    check("the projector says so in its notes rather than returning it silently",
          any("doubly occupied" in n for n in ps.notes),
          f"notes: {ps.notes}")

    print("\nWith sigma targets, every hydride gets virtual orbitals")
    for name, mol in (("water", WATER), ("ammonia", AMMONIA), ("methane", METHANE)):
        for basis in BASES:
            ps = _pool(*mol, basis, include_sigma=True)
            ne, no = sum(ps.nelecas), ps.ncas
            check(f"{name}/{basis}: CAS({ne},{no}) has "
                  f"{no - ne // 2} virtual orbitals",
                  ne < 2 * no, f"CAS({ne},{no}) is full -- no correlation to describe")

    print("\nThe hydride pools are basis independent too")
    for name, mol in (("water", WATER), ("ammonia", AMMONIA), ("methane", METHANE)):
        spaces = {b: (lambda p: (sum(p.nelecas), p.ncas))(_pool(*mol, b, True))
                  for b in BASES}
        check(f"{name}: identical across {', '.join(BASES)}",
              len(set(spaces.values())) == 1,
              "  ".join(f"{b}:{s}" for b, s in spaces.items()))

    print("\nand rotation independent")
    rng = np.random.default_rng(20260902)
    syms, co = WATER
    ref = (lambda p: (sum(p.nelecas), p.ncas))(_pool(syms, co, "cc-pvdz", True))
    got = {(lambda p: (sum(p.nelecas), p.ncas))(
        _pool(syms, co @ _rot(rng).T, "cc-pvdz", True)) for _ in range(5)}
    check(f"water: 5 random rotations all give CAS{ref}", got == {ref},
          f"got {sorted(got)}")

    print("\nThe carbonyl lone pair survives into the space -- without it the "
          "dark n->pi* state has no hole orbital")
    ps = _pool(*CH2O, "cc-pvdz", include_sigma=False)
    ne, no = sum(ps.nelecas), ps.ncas
    check(f"formaldehyde, pi+lone-pair: CAS({ne},{no}) is larger than the "
          f"pi-only CAS(2,2), so the n orbitals are in",
          no >= 3 and ne < 2 * no, f"got CAS({ne},{no})")
    check("the pool carries a lone-pair-derived target",
          any("lone_pair" in lbl for lbl in ps.target_labels),
          f"labels: {ps.target_labels}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
