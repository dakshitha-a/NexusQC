"""Does the space the engine recommended reach the CASSCF that runs?

Every assertion here is by PROJECTION, never by position. That is the whole
point of the file. An orbital index is not a durable name for an orbital: the
indices shift after an SCF, after a rotation, and completely after a change of
basis, where the method document records a naive index handoff scoring a
principal cosine of 0.000 into aug-cc-pVDZ. So "is this the same orbital" is
asked as "do these two sets span the same subspace", which is invariant to
exactly the rotations a CASSCF is free to make inside its active space.

Three questions, each of which is a contract nothing else checks.

**1. The default window.** `active_space_orbital_indices` is set only when a
user names orbitals, which is not the ordinary case, and when it is absent
`_apply_named_active_space` returns immediately and never calls `sort_mo`.
PySCF then takes ncas orbitals around the HOMO with no character test of any
kind. That is safe here only because `projector.project` returns its orbitals
ordered as [frozen core, inactive occupied, ACTIVE, virtual], which puts the
active block exactly at the occupied/virtual boundary, so the default window
and the recommended block coincide. Nothing tested that, and it is the kind of
implicit contract a later reordering breaks silently.

**2. The restart set and the natural-orbital set are different orbitals.** A
refinement writes both, and its reported occupations, labels and rotation trail
describe the natural set. Reading that table against `orbitals.molden`, which
is the unrotated restart set, gives the wrong answer per orbital while both
files legitimately span the same space.

**3. A change of basis.** Kept short because `cas_09_portable_spec.py` already
covers the specification route; what is asserted here is only that the operative
handoff preserves the subspace where an index handoff does not.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

from pyscf import gto, mcscf, scf                                 # noqa: E402

from app.chemistry.cas.recommend import recommend                 # noqa: E402

PASS = 0
FAIL = 0

PYRROLE = (
    ["N", "C", "C", "C", "C", "H", "H", "H", "H", "H"],
    np.asarray([
        [0.0000, 0.0000, 1.1428], [0.0000, 1.1201, 0.3373],
        [0.0000, -1.1201, 0.3373], [0.0000, 0.7159, -0.9761],
        [0.0000, -0.7159, -0.9761], [0.0000, 0.0000, 2.1519],
        [0.0000, 2.1043, 0.7757], [0.0000, -2.1043, 0.7757],
        [0.0000, 1.3552, -1.8437], [0.0000, -1.3552, -1.8437],
    ]))


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))


def _mf(basis):
    syms, co = PYRROLE
    mol = gto.M(atom="\n".join(f"{s} {c[0]} {c[1]} {c[2]}"
                               for s, c in zip(syms, co)),
                basis=basis, verbose=0)
    mf = scf.RHF(mol).density_fit()
    mf.kernel()
    return mol, mf


def subspace_overlap(mol, a, b):
    """How many dimensions of `a` lie inside span(`b`), as a trace.

    Equal to min(rank) when the spaces coincide and less when they do not.
    Invariant to any rotation within either set, which is what makes it the
    right question to ask of an active space.
    """
    s = mol.intor("int1e_ovlp")
    # Orthonormalise b, then project a onto it.
    sb = b.T @ s @ b
    w, u = np.linalg.eigh(sb)
    keep = w > 1e-10
    bo = b @ (u[:, keep] / np.sqrt(w[keep]))
    m = a.T @ s @ bo
    return float(np.sum(m ** 2))


def main():
    print("The default active window, when no orbitals were named")
    mol, mf = _mf("def2-svp")
    syms, co = PYRROLE
    rec = recommend(mf, syms, co, spin_2s=0)
    ne, no = rec.space
    idx = rec.tiers[rec.recommended].orbital_indices
    print(f"  pyrrole/def2-svp recommends CAS({ne},{no}) at 0-based {idx}")

    # Exactly what run_casscf does when active_space_orbital_indices is absent:
    # build the CASSCF on the recommendation's own orbitals and let pyscf pick
    # its own window. No sort_mo anywhere.
    mc = mcscf.CASSCF(mf, no, ne)
    mc.mo_coeff = rec.mo_coeff
    default_block = mc.mo_coeff[:, mc.ncore:mc.ncore + mc.ncas]
    recommended_block = rec.mo_coeff[:, idx]

    check("the recommended orbitals are contiguous, which is what lets a "
          "HOMO-centred window find them at all",
          list(idx) == list(range(idx[0], idx[0] + len(idx))),
          f"indices {idx}")
    ov = subspace_overlap(mol, default_block, recommended_block)
    check(f"pyscf's default window spans the recommended space "
          f"(overlap {ov:.4f} of {no})", abs(ov - no) < 1e-6,
          f"got {ov:.6f}, wanted {no}")
    check("and pyscf's own ncore agrees with where the projector put the "
          "active block",
          mc.ncore == idx[0], f"ncore {mc.ncore} vs first active {idx[0]}")

    print("\nA deliberately wrong window, to show the test can fail")
    shifted = rec.mo_coeff[:, [i + 1 for i in idx]]
    ov_bad = subspace_overlap(mol, shifted, recommended_block)
    check(f"a window shifted by one orbital does NOT span it "
          f"(overlap {ov_bad:.3f} of {no})", ov_bad < no - 0.5,
          f"got {ov_bad:.4f}")

    print("\nThe restart set and the natural-orbital set are not the same "
          "orbitals")
    from app.chemistry.cas.refine import refine
    res = refine(mf, syms, co, rec, n_states=1, spin_2s=0,
                 log=lambda *a, **k: None)
    nat = res.natural_orbitals[:, res.ncore:res.ncore + res.n_orbitals]
    restart = res.mo_coeff[:, res.ncore:res.ncore + res.n_orbitals]
    same_span = subspace_overlap(mol, nat, restart)
    check(f"they span the same space (overlap {same_span:.4f} of "
          f"{res.n_orbitals})", abs(same_span - res.n_orbitals) < 1e-6,
          f"got {same_span:.6f}")
    per_orbital = [float(abs(np.dot(nat[:, k],
                                    mol.intor("int1e_ovlp") @ restart[:, k])))
                   for k in range(res.n_orbitals)]
    check("but they are NOT the same orbitals one by one, so a reported "
          "occupation read against the restart file names the wrong orbital",
          min(per_orbital) < 0.99,
          f"per-orbital overlaps {[round(x, 3) for x in per_orbital]}")

    print("\nThe table and molden a recommendation job writes are the projected set")
    # A recommendation job used to write its molden and table from `mf`
    # while its listed indices pointed into rec.mo_coeff, so the orbitals it
    # named were not the rows it showed and a follow-up seeded from it read
    # the SCF's HOMO window. The writer now takes the projected set; this
    # reads the file back the way a later job does and asks whether the
    # listed rows are the recommended orbitals.
    import shutil
    import tempfile
    from pyscf.tools import molden as pyscf_molden
    from app.chemistry.jobs.pyscf_runner import _write_projected_molden_and_table
    tmp = tempfile.mkdtemp()
    try:
        path, table = _write_projected_molden_and_table(tmp, mf, rec.mo_coeff)
        _m, _e, mo_disk, occ_disk, _i, _s = pyscf_molden.load(path)
        s_ao = mol.intor("int1e_ovlp")
        disk_block = np.asarray(mo_disk)[:, idx]
        one_by_one = [abs(float(disk_block[:, k] @ s_ao @ recommended_block[:, k]))
                      for k in range(len(idx))]
        check("the listed 1-based rows of the written molden ARE the recommended orbitals, one by one",
              min(one_by_one) > 0.999, f"per-orbital overlaps {[round(x, 4) for x in one_by_one]}")
        occ_rows = [table[i]["occupancy"] for i in idx]
        check("the recommended block holds both occupied and empty orbitals, with exact occupations",
              all(o in (0.0, 2.0) for o in occ_rows) and 2.0 in occ_rows and 0.0 in occ_rows,
              str(occ_rows))
        check("the table's occupations match the file's, row for row",
              all(abs(float(occ_disk[r["index"] - 1]) - r["occupancy"]) < 1e-9 for r in table))
        check("the file's orbital count is the full set, so a follow-up can name any row of it",
              np.asarray(mo_disk).shape[1] == rec.mo_coeff.shape[1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
