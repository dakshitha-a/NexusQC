"""Can this calculation describe a diffuse orbital at all?

The question matters because of what the answer gates. `excited._label` will
only call a state Rydberg when the engine believes Rydberg states are
detectable, so a wrong answer here does not merely suppress a note: a genuine
Rydberg state gets labelled as a valence one, and `excited.augment`'s Rydberg
exclusion cannot fire on a state it was never told is Rydberg. A diffuse
orbital then goes into a valence active space, which the method document
describes as a reliable way to make a CASSCF hard to converge for no gain.

**This replaces an exponent threshold that did not work.** `basis_has_diffuse`
asked whether the smallest primitive exponent anywhere in the molecule fell
below 0.05, on the reasoning that cc-pVDZ's smallest is about 0.15 and
aug-cc-pVDZ's about 0.04. That cut is element dependent and it fails in both
directions, measured on this host:

- `def2-svpd`, which is the engine's OWN default analysis basis whenever
  excited states are requested, bottoms out at 0.067 for carbon and was
  therefore reported as carrying no diffuse functions. Every production
  excited-state recommendation was telling the user Rydberg states had not
  been looked for. Measured on formaldehyde, that basis puts the n->Rydberg 3s
  state at 7.50 eV against a QUEST reference of 7.30 with a second-moment
  ratio of 3.24, comfortably over the Rydberg cut, so the state was being
  found and mislabelled at the same time as the user was told it could not be.
- `aug-cc-pVDZ` on N2 (smallest 0.056) and on F2 (0.085) was likewise reported
  as carrying none, because those elements' augmenting shells are less diffuse
  in absolute terms than carbon's ordinary valence ones.

`app/chemistry/jobs/molden.py` had already reached this conclusion and wrote
it down: "no threshold separates the bases cleanly -- cc-pVTZ's smallest is
0.1027 and ma-def2-SVP's is 0.0851, so any cut between them would be luck
rather than physics." That module measured the orbitals instead. The engine
did not, and the two contradicted each other. This module is the measurement,
shared, so there is one answer rather than two.

The measure is the fraction of an orbital's own density lying outside 1.5 van
der Waals radii of every atom, which is scale free and so does not need a
per-element table. It lives under `cas/` rather than under `jobs/` because
`app/chemistry/cas/` is a library over a converged mean field and must not
import the job layer, while the job layer may import it.
"""
from __future__ import annotations

import numpy as np
from pyscf.data import radii
from pyscf.dft import gen_grid, numint

# Blocked so a large molecule never materializes a points-by-orbitals array.
_GRID_BLOCK = 8000

# Above this fraction an orbital is called diffuse. Occupied orbitals sit below
# 0.01 in practice and non-augmented bases produce nothing above about 0.39,
# measured here over water, formaldehyde, N2 and F2 in six basis sets, while
# augmented ones reach 0.95. This is the same constant `molden.py` reports its
# orbital table against, deliberately, so the table and the Rydberg gate cannot
# disagree about what "diffuse" means.
DIFFUSE_FRACTION = 0.5


def build_grid(mol):
    """A Becke grid at level 1, returned as (coords, weights).

    Level 1 rather than the cheaper level 0, and the reason is the diffuse
    fraction rather than any symmetry test. A diffuse orbital keeps most of its
    norm in the grid's sparse outer shells: on water/aug-cc-pVDZ, level 0
    recovers 1.019 of the analytic norm for the lowest Rydberg-like virtual
    where level 1 gives 1.0004. A 2% error on the integral a fraction is taken
    from is not worth the saving, and level 1 costs about 0.13 s on uracil.
    """
    grids = gen_grid.Grids(mol)
    grids.level = 1
    grids.build()
    return grids.coords, grids.weights


def diffuse_fractions(mol, mo_coeff: np.ndarray, grid=None) -> np.ndarray:
    """For each column of `mo_coeff`, the fraction of its own density lying
    outside the molecule, where outside means further than 1.5 van der Waals
    radii from every atom.

    The measure is a fraction rather than a radius so that it does not scale
    with the molecule. Across water, formaldehyde, ethylene, benzene and
    uracil, every occupied orbital comes in below 0.010 and every cc-pVDZ
    virtual below 0.29, while aug-cc-pVDZ virtuals reach 0.98. The 1.5
    multiplier is what puts valence antibonding orbitals inside: at a bare van
    der Waals radius, water's cc-pVDZ sigma* orbitals read 0.55 and 0.61,
    which would be indistinguishable from a genuinely diffuse one.

    Deliberately not called a Rydberg test. Separating a true Rydberg series
    member from a diffuse virtual needs a principal quantum number and a
    quantum defect, not a spatial extent. This reports what it measured.

    `grid` is accepted so a caller already holding one does not build a second.
    """
    coords, weights = build_grid(mol) if grid is None else grid
    atom_coords = mol.atom_coords()
    vdw = np.array([radii.VDW[mol.atom_charge(ia)] for ia in range(mol.natm)])
    out = np.zeros(mo_coeff.shape[1])
    total = np.zeros(mo_coeff.shape[1])
    for start in range(0, len(coords), _GRID_BLOCK):
        pts = coords[start:start + _GRID_BLOCK]
        wts = weights[start:start + _GRID_BLOCK]
        outside = (np.linalg.norm(pts[:, None, :] - atom_coords[None, :, :], axis=2)
                   > 1.5 * vdw[None, :]).all(axis=1)
        density = (numint.eval_ao(mol, pts) @ mo_coeff) ** 2
        total += wts @ density
        out += (wts * outside) @ density
    return np.divide(out, total, out=np.zeros_like(out), where=total > 1e-12)


def rydberg_representable(mf, grid=None) -> bool:
    """Whether THIS calculation offers an orbital diffuse enough to host a
    Rydberg state.

    A statement about the calculation rather than about the basis set's name,
    which is what makes it correct where an exponent rule was not. A basis that
    augments carbon usefully may do little for fluorine, and a compact molecule
    in a nominally augmented basis may still have nothing diffuse to offer: N2
    in def2-svpd reaches only 0.347 and F2 in aug-cc-pVDZ only 0.429, and for
    those two the honest answer really is that no Rydberg state can be
    described here. Reporting that per calculation is more useful than
    reporting a property of the basis that may not hold for the atoms in it.

    **Which mean field you ask matters, and the margin is not large.** Kohn-Sham
    virtuals are bound in the same potential as the occupied set and so are
    systematically more compact than Hartree-Fock ones. Measured over four
    molecules in three basis sets, every KS fraction is 0.02 to 0.08 below its
    RHF counterpart: formaldehyde/def2-svpd goes 0.651 to 0.571 against a 0.5
    cut. All twelve pairs still agree on the answer, but the closest case sits
    0.024 above the threshold, so this should be evaluated ONCE per job on the
    SCF reference and passed to whatever needs it, rather than recomputed on
    the CAM-B3LYP reference the TDA pass runs on. `analyse` therefore takes it
    as an argument. Recomputing would also build a second Becke grid for no
    reason.

    Returns False rather than raising if the reference has no virtual orbitals
    at all, which is a minimal basis on a closed-shell atom and not a case
    worth an exception.
    """
    occ = np.asarray(mf.mo_occ)
    mo = np.asarray(mf.mo_coeff)
    if mo.ndim == 3:
        # An unrestricted reference hands back a stacked (2, nao, nmo) pair.
        # Slicing that with a boolean mask silently misindexes rather than
        # raising, so take the alpha set explicitly. The engine uses ROHF by
        # measurement (see the method document, section 4.5) and so does not
        # reach this, but a caller passing UHF should get an answer rather than
        # a quietly wrong one.
        mo, occ = mo[0], np.asarray(occ)[0]
    virtual = mo[:, occ == 0]
    if virtual.shape[1] == 0:
        return False
    return bool(np.max(diffuse_fractions(mf.mol, virtual, grid)) > DIFFUSE_FRACTION)
