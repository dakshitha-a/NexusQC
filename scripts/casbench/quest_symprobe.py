#!/usr/bin/env python3
"""Phase 0 probe for the QUESTDB benchmark (docs/casbench/questdb-phase0.md).

Two questions, both about whether King et al.'s protocol can be applied to the
NexusQC engine at all:

1. Is the engine's active space irrep-closed when the molecule is built with
   symmetry on? King's state averages target irreps (`wfnsym`), which needs
   every active orbital to belong to one irrep. For each tier the span is
   projected onto each irrep's S-orthonormal symmetry orbitals; a singular
   value of 1 is a direction wholly inside the span, 0 wholly outside, and
   anything in between is printed because it means the span mixes irreps.
2. Can a TDA be restricted to one irrep (`td.wfnsym`), and to triplets, and
   still be fed through the engine's `analyse` and `add_state_narrowed_tier`?

Geometries are King's own (QUESTDB CC3/aug-cc-pVTZ, in bohr), read from the
converted Jun88 records that `quest_unpickle.py` writes.

    python3 scripts/casbench/quest_symprobe.py
"""
import sys, time, json
from pathlib import Path
import numpy as np
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pyscf import gto, scf, dft, tdscf, symm, lib
from app.chemistry.cas.recommend import recommend
from app.chemistry.cas.reference import stabilise
from app.chemistry.cas.excited import analyse
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.narrow import add_state_narrowed_tier
from app.chemistry.cas.diffuse import rydberg_representable

BOHR = 0.52917721092
NPZ = REPO / ".cache" / "casbench_quest" / "king_npz" / "Jun88"

def load(name):
    """Symbols and coordinates in Angstrom, which is what the engine expects."""
    meta = json.load(open(NPZ / f"{name}-x1.json"))["metadata"]
    scale = BOHR if meta["unit"].lower().startswith("b") else 1.0
    return ([s for s, _ in meta["geom"]],
            np.array([xyz for _, xyz in meta["geom"]], float) * scale)

def closure(mol, C, S):
    """Fraction of the active span inside each irrep, and the largest
    out-of-span leakage after projecting each irrep component back."""
    P = C @ C.T @ S            # projector onto span (AO, S-metric)
    leak = 0.0; dims = {}
    for ir, so in zip(mol.irrep_name, mol.symm_orb):
        # component of span in irrep: project SO basis into span
        w, v = np.linalg.eigh(so.T @ S @ so)
        so = so @ v @ np.diag(w ** -0.5) @ v.T      # S-orthonormal SOs
        M = so.T @ S @ C        # (nso, ncas)
        sv = np.linalg.svd(M, compute_uv=False)
        dims[ir] = int(np.sum(sv > 0.999))
        if np.any((sv > 0.01) & (sv < 0.999)): print("     ", ir, np.round(sv, 4))
        leak = max(leak, float(np.sum((sv > 0.01) & (sv < 0.999))))
    return dims, leak

SUB = {"ch": "C2v", "cn": "C2v", "no": "C2v", "beh": "C2v", "bef": "C2v", "oh": "C2v", "co+": "C2v"}

def run(name, basis, spin=0, charge=0, wfn=None, nst=2):
    syms, co = load(name)
    t0 = time.time()
    mol = gto.M(atom=list(zip(syms, co)), basis=basis, spin=spin, charge=charge,
                symmetry=True, symmetry_subgroup=SUB.get(name), verbose=0)
    mf = (scf.RHF(mol) if spin == 0 else scf.ROHF(mol)).density_fit(auxbasis=__import__("pyscf").df.make_auxbasis(mol)); mf.kernel()
    stabilise(mf, check_external=False)
    rec = recommend(mf, syms, co, spin_2s=spin, n_states=nst)
    S = mol.intor("int1e_ovlp")
    t = rec.tiers[rec.recommended]
    ne, no = rec.space
    C = rec.mo_coeff[:, rec.ncore:rec.ncore+no] if hasattr(rec, "ncore") else None
    print(f"{name} {basis} pg={mol.groupname} nao={mol.nao} space=({ne},{no}) t={time.time()-t0:.1f}s")
    return mol, mf, rec, S, syms, co


def probe(name, basis, spin=0, wfnsym=None, j=1, triplet=False):
    mol, mf, rec, S, syms, co = run(name, basis, spin=spin, nst=j + 1)
    for tn, t in rec.tiers.items():
        C = rec.mo_coeff[:, t.orbital_indices]
        dims, leak = closure(mol, C, S)
        print(f"  tier {tn:12s} ({t.n_electrons},{t.n_orbitals}) irrep dims={dims} "
              f"sum={sum(dims.values())} partially-in-span dirs={leak:.0f}")
    if wfnsym is None:
        return
    ks = (dft.RKS(mol) if spin == 0 else dft.ROKS(mol)); ks.xc = "camb3lyp"
    ks = ks.density_fit(auxbasis=__import__("pyscf").df.make_auxbasis(mol)); ks.kernel()
    td = tdscf.TDA(ks)
    if triplet:
        td.singlet = False
    td.wfnsym = wfnsym
    td.nstates = max(6, 2 * j + 2)
    td.kernel()
    print(f"  TDA wfnsym={wfnsym} triplet={triplet} E(eV)=",
          np.round(td.e * 27.2114, 2)[:6])
    per = perceive(syms, co, include_sigma=False)
    an = analyse(ks, td, per.targets, n_states=j,
                 rydberg_detectable=bool(rydberg_representable(ks)))
    for s in an.states[:j + 1]:
        print(f"    S{s.index} {s.energy_ev:.2f} {s.character}")
    added = add_state_narrowed_tier(rec, mol, an, j + 1, per.targets,
                                    perception=per, spin_2s=spin)
    t = rec.tiers[rec.recommended]
    C = rec.mo_coeff[:, t.orbital_indices]
    dims, leak = closure(mol, C, S)
    print(f"  narrowed added={added} -> {rec.recommended} ({t.n_electrons},{t.n_orbitals}) "
          f"dims={dims} partial={leak:.0f}")


CASES = [("water", "A2", 0, False), ("formaldehyde", "A2", 0, False),
         ("formaldehyde", "A2", 0, True), ("ethylene", "B1u", 0, False),
         ("pyrazine", "B3u", 0, False), ("allyl", "A1", 1, False),
         ("beh", "B1", 1, False), ("ch", "A2", 1, False), ("bef", "A1", 1, False)]

if __name__ == "__main__":
    basis = sys.argv[1] if len(sys.argv) > 1 else "cc-pvdz"
    for name, wfn, spin, trip in CASES:
        try:
            probe(name, basis, spin=spin, wfnsym=wfn, j=1, triplet=trip)
        except Exception as exc:                                # noqa: BLE001
            print(f"{name} FAILED {type(exc).__name__}: {str(exc)[:200]}")
