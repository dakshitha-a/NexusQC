#!/usr/bin/env python3
"""QUESTDB vertical-excitation benchmark for active-space selection.

Runs one excitation from King, Hermes, Truhlar and Gagliardi's 542-row set
(JCTC 2022, 18, 6065) through one fixed protocol, with the active space chosen
by one of three selectors:

    apc2           King's own selector: APC-2 entropies on Boys-localised
                   orbitals (23 occupied + 23 virtual, localised within each
                   irrep), cut to max(12,12) = 226,512 CSFs. The control.
    engine         the NexusQC engine's space exactly as the product would
                   return it for the requested state, symmetrised.
    engine_capped  the engine's space cut to the same CSF budget as apc2 by
                   the same rule (drop the lowest APC entropy first), which
                   separates WHICH orbitals the engine picks from HOW MANY.

Everything after the selection is shared and is King's protocol, read per row
from his Zenodo record through `.cache/casbench_quest/manifest.json`
(`quest_fetch.py` builds it): geometry, basis, charge, spin, symmetry, the
exact state average (irreps, spins, equal weights), CASSCF settings and the
MC-PDFT grid. Then SA-CASSCF, tPBE and tPBE0 (= 0.75 tPBE + 0.25 CASSCF),
SC-NEVPT2, and the M diagnostic of the ground and target states. Phase 0
(docs/casbench/questdb-phase0.md) is the evidence that this downstream code
reproduces King's numbers from King's wavefunctions.

One row at a time, as a subprocess, so a crash in PySCF costs one row:

    python3 scripts/casbench/quest_bench.py one <name> <mode> [--out results.jsonl]

The pool, checkpointing and restart handling are in `quest_run.py`, driven by
`quest_ctl.sh`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np

# PySCF reads its global memory budget once, at import, from this variable.
# The CSF solver's spin-coupling transformer is built with that global
# default whatever the solver's own `max_memory` says, and compares it with
# the process's whole resident size: at the default 4000 MB an aug-cc-pVTZ
# allyl job asks for 0.004 MB and is refused with "-481 MB remaining". Set
# before any PySCF import, which in this module are all inside functions.
os.environ.setdefault("PYSCF_MAX_MEMORY", os.environ.get("QUEST_MAX_MEMORY_MB", "16000"))

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
CACHE = REPO / ".cache" / "casbench_quest"
HARTREE_TO_EV = 27.211386245988
MAX_CSF = 226512                        # max(12,12), King's Aug(12,12) cap
GOOD_SPACE_EV = 1.1                     # King's |SA-CASSCF - TBE| filter
SS_TO_SMULT = {0.0: 1, 0.75: 2, 2.0: 3}


# ---------------------------------------------------------------- molecule

def basis_name(b: str):
    """King's metadata spells bases 'aug-ccpvtz', 'jun-ccpvtz', 'ccpvdz'."""
    k = b.replace("-", "").lower()
    return {"augccpvtz": "aug-cc-pvtz", "ccpvtz": "cc-pvtz", "ccpvdz": "cc-pvdz",
            "junccpvtz": "jun-cc-pvtz"}.get(k, b)


def build_mol(row, basis=None, verbose=0):
    from pyscf import gto
    b = basis_name(basis or (row.get("solver") or {}).get("basis") or "aug-ccpvtz")
    if b == "jun-cc-pvtz":
        text = open(CACHE / "zenodo" / "jun-cc-pvtz.dat").read()
        b = {el: gto.basis.parse(text, symb=el) for el in {s for s, _ in row["geometry"]}}
    mol = gto.Mole()
    mol.atom = [(s, xyz) for s, xyz in row["geometry"]]
    mol.unit = row["geometry_unit"]
    mol.basis = b
    mol.charge = row["charge"]
    mol.spin = row["spin"]
    # King's records store `hf_symmetry` as True or as a group name: linear
    # molecules were run in C2v rather than Coov/Dooh, and their orbitals are
    # only symmetry-adapted in that group.
    mol.symmetry = row.get("symmetry", True)
    if row.get("symmetry_subgroup"):
        mol.symmetry_subgroup = row["symmetry_subgroup"]
    mol.verbose = verbose
    mol.max_memory = int(os.environ.get("QUEST_MAX_MEMORY_MB", "16000"))
    mol.build()
    return mol


# --------------------------------------------------------------- reference

def reference_scf(mol, row, cache=True, log=print):
    """One conventional RHF/ROHF per molecule, symmetry on, stabilised.

    Shared by every selector and every excitation of the molecule, so a
    selector cannot win by starting from a different mean field. The final
    mean field has no density fitting: King ran without it, Phase 0
    reproduced him without it.

    Stability is analysed on a density-fitted copy first and the
    conventional SCF is then converged from that stabilised density. On
    pyrazine in aug-cc-pVTZ the stability analysis costs 398 s with full
    integrals and the whole route below about a minute and a half, for the
    same converged energy. Beryllium has no JK fitting basis in PySCF, so
    the fitting basis is generated (`make_auxbasis`) rather than looked up.
    The converged orbitals are cached per molecule and basis.
    """
    from pyscf import df, scf
    from app.chemistry.cas.reference import stabilise
    bname = mol.basis if isinstance(mol.basis, str) else "custom"
    key = f"{row['molecule']}_{row['charge']}_{row['spin']}_{bname}"
    chk = CACHE / "scf" / f"{key}.npz"
    mk = (lambda: scf.RHF(mol)) if mol.spin == 0 else (lambda: scf.ROHF(mol))
    mf = mk()
    mf.verbose = 0
    mf.conv_tol = 1e-10
    if cache and chk.exists():
        z = np.load(chk)
        mf.kernel(dm0=mf.make_rdm1(z["mo_coeff"], z["mo_occ"]))
        return mf, {"cached": True, "energy": float(mf.e_tot),
                    "stabilised_shift_eh": float(z["shift"])}
    t0 = time.time()
    mfd = mk().density_fit(auxbasis=df.make_auxbasis(mol))
    mfd.verbose = 0
    mfd.kernel()
    e0 = float(mfd.e_tot)
    stabilise(mfd, check_external=False)
    shift = float(mfd.e_tot) - e0
    mf.kernel(dm0=mfd.make_rdm1())
    info = {"cached": False, "energy": float(mf.e_tot), "converged": bool(mf.converged),
            "stabilised_shift_eh": shift, "seconds": round(time.time() - t0, 1)}
    log(f"  SCF {mol.nao} AO  E={mf.e_tot:.8f}  stabilise moved it {shift:+.2e} Eh  "
        f"{info['seconds']}s")
    if cache:
        chk.parent.mkdir(parents=True, exist_ok=True)
        tmp = chk.with_name(chk.stem + f".tmp{os.getpid()}.npz")
        np.savez(tmp, mo_coeff=mf.mo_coeff, mo_occ=mf.mo_occ, shift=shift)
        os.replace(tmp, chk)
    return mf, info


# ---------------------------------------------------------------- selectors

def _irrep_blocks(mol, C, S):
    """Split orbitals that are each in one irrep into per-irrep column groups."""
    from pyscf import symm
    orbsym = symm.label_orb_symm(mol, mol.irrep_id, mol.symm_orb, C, s=S, check=False)
    out = {}
    for k, ir in enumerate(orbsym):
        out.setdefault(int(ir), []).append(k)
    return out


def apc2_candidates(mf, mol, n_window=23):
    """King's candidate orbitals: up to 23 highest doubly occupied and up to
    23 lowest virtual canonical orbitals, each set grouped by irrep and
    Boys-localised within each irrep, plus any singly occupied orbital as is.

    Returns (C_candidates, occ_candidates, other_occupied_idx,
    other_virtual_idx). Every orbital outside the window
    is not a candidate: occupied ones end up in the core, virtual ones in
    the secondary space, whatever their entropy would have been.
    """
    from pyscf import lo
    S = mol.intor_symmetric("int1e_ovlp")
    occ = np.asarray(mf.mo_occ)
    e = np.asarray(mf.mo_energy)
    docc = [i for i in np.argsort(e) if occ[i] == 2][-n_window:]
    socc = [i for i in range(len(occ)) if occ[i] == 1]
    virt = [i for i in np.argsort(e) if occ[i] == 0][:n_window]
    cols, occs = [], []
    for group, o in ((sorted(docc), 2), (sorted(virt), 0)):
        C = mf.mo_coeff[:, group]
        for ir, ks in sorted(_irrep_blocks(mol, C, S).items()):
            block = C[:, ks]
            if block.shape[1] > 1:
                loc = lo.Boys(mol, block)
                loc.verbose = 0
                block = loc.kernel()
            cols.append(block)
            occs += [o] * block.shape[1]
    for i in socc:
        cols.append(mf.mo_coeff[:, [i]])
        occs.append(1)
    rest_occ = [i for i in range(len(occ)) if occ[i] == 2 and i not in docc]
    rest_virt = [i for i in range(len(occ)) if occ[i] == 0 and i not in virt]
    return np.hstack(cols), np.asarray(occs, float), rest_occ, rest_virt


def select_apc2(mf, mol, max_size=(12, 12), log=print):
    """APC-2 ranking over King's candidates, cut to max_size by CSF count.

    PySCF's `mcscf.apc.APC` ranks whatever orbitals the mean field carries and
    builds F and K from that object. It is handed a copy whose orbitals are
    the candidates and whose `get_fock`/`get_k` return the FULL mean field's
    matrices, so the entropies are King's: diagonal F and K over the
    candidate set only, with N = 2 dropout and eps = 1e-3.
    """
    from pyscf.mcscf.apc import APC, Chooser
    Cc, occ, rest_occ, rest_virt = apc2_candidates(mf, mol)
    F = mf.get_fock()
    K = mf.get_k()
    proxy = mf.copy()
    proxy.mo_coeff = Cc
    proxy.mo_occ = occ
    proxy.get_fock = lambda *a, **k: F
    proxy.get_k = lambda *a, **k: K
    apc = APC(proxy, max_size=max_size, n=2, eps=1e-3, verbose=0)
    ent = apc._calc_apc_entropies(proxy)
    # The chooser wants the whole orbital set. Orbitals outside King's window
    # are not candidates, so they are given an entropy below every candidate's
    # and are the first dropped; the occupied ones fall into the core and the
    # virtual ones into the secondary space, as in King's protocol.
    floor = float(np.min(ent)) - 1.0
    orbs = np.hstack([mf.mo_coeff[:, rest_occ], Cc, mf.mo_coeff[:, rest_virt]])
    occ_all = np.concatenate([np.full(len(rest_occ), 2.0), occ, np.zeros(len(rest_virt))])
    ent_all = np.concatenate([np.full(len(rest_occ), floor), ent,
                              np.full(len(rest_virt), floor)])
    # An aug-cc-pVTZ SCF on a linear molecule can drop a near-linearly
    # dependent AO combination (diacetylene: 230 AOs, 229 MOs), and the
    # chooser asserts a square orbital matrix. It only ever reads the matrix
    # to return columns, so the missing columns are padded with zeros that
    # carry the floor entropy and no electrons, and are always dropped.
    pad = orbs.shape[0] - orbs.shape[1]
    if pad > 0:
        orbs = np.hstack([orbs, np.zeros((orbs.shape[0], pad))])
        occ_all = np.concatenate([occ_all, np.zeros(pad)])
        ent_all = np.concatenate([ent_all, np.full(pad, floor)])
    ncas, nelecas, casorbs, active_idx = Chooser(
        orbs, occ_all, ent_all, max_size, verbose=0).kernel()
    nel = int(round(np.sum(nelecas))) if hasattr(nelecas, "__len__") else int(nelecas)
    log(f"  APC-2 picked ({nel},{ncas}) from {Cc.shape[1]} candidates")
    # `casorbs` is the whole reordered set (inactive | active | secondary);
    # the active columns are the ones the chooser kept.
    return orbs[:, list(active_idx)], nel, {"n_candidates": int(Cc.shape[1]),
                          "entropies": [float(x) for x in ent]}


def ncsf(nel: int, norb: int) -> int:
    """King's eq 4: CSFs at the lowest Ms, the count his size cap is set in."""
    from math import comb
    a, b = nel // 2 + nel % 2, nel // 2
    return comb(norb, a) * comb(norb, b) - (comb(norb, a + 1) * comb(norb, b - 1) if b >= 1 else 0)


def cap_by_entropy(occ, ent, max_csf=MAX_CSF):
    """Drop the lowest-entropy orbital until the space fits, King's rule.

    Same loop as PySCF's `apc.Chooser`: at each step the lowest-entropy
    orbital whose removal leaves a reasonable space goes, where reasonable
    means some active electrons, not completely full, and no fewer orbitals
    than there are singly occupied ones. Returns the kept indices.
    """
    keep = list(range(len(occ)))
    n_so = int(sum(1 for o in occ if o == 1))
    while ncsf(int(sum(occ[k] for k in keep)), len(keep)) > max_csf:
        for k in sorted(keep, key=lambda k: ent[k]):
            trial = [x for x in keep if x != k]
            nel = sum(occ[x] for x in trial)
            if nel > 0 and nel < 2 * len(trial) and len(trial) >= n_so:
                keep = trial
                break
        else:
            raise RuntimeError("no reasonable space under the cap")
    return keep


def _occupancy(mol, mf, C):
    """Each orbital's occupation in the reference: 2, 1 or 0 for a pure one."""
    S = mol.intor_symmetric("int1e_ovlp")
    occ = np.asarray(mf.mo_occ)
    D = mf.mo_coeff[:, occ == 2]
    Sg = mf.mo_coeff[:, occ == 1]
    w2 = np.sum((D.T @ S @ C) ** 2, axis=0) if D.size else np.zeros(C.shape[1])
    w1 = np.sum((Sg.T @ S @ C) ** 2, axis=0) if Sg.size else np.zeros(C.shape[1])
    return 2 * w2 + w1


def select_engine(mf, mol, row, capped=False, log=print):
    """The NexusQC engine's space for this row's target state.

    Mirrors `pyscf_runner.run_cas_recommendation` for a request of the
    target state: recommend on the shared reference, a CAM-B3LYP TDA for the
    states, the engine's own `analyse` and `add_state_narrowed_tier`. Two
    things go beyond what the product can be asked, and the ledger says so.
    The TDA is restricted to the target's irrep (`wfnsym`), so its lowest
    `target_rank` roots are exactly the states of that irrep King's average
    contains. And for a triplet target the TDA is a triplet one: the product
    only ever runs singlet linear response.
    """
    from pyscf import df, dft, tdscf
    from app.chemistry.cas.diffuse import rydberg_representable
    from app.chemistry.cas.excited import analyse
    from app.chemistry.cas.geometry import perceive
    from app.chemistry.cas.narrow import add_state_narrowed_tier
    from app.chemistry.cas.recommend import recommend
    t0 = time.time()
    syms = [mol.atom_symbol(i) for i in range(mol.natm)]
    coords = mol.atom_coords(unit="Angstrom")
    rank = int(row["target_rank"])
    n_states = rank + 1
    rec = recommend(mf, syms, coords, spin_2s=mol.spin, n_states=n_states)
    pool_space = list(rec.space)
    ks = dft.RKS(mol) if mol.spin == 0 else dft.ROKS(mol)
    ks.xc = "camb3lyp"
    ks = ks.density_fit(auxbasis=df.make_auxbasis(mol))
    ks.verbose = 0
    ks.kernel()
    td = tdscf.TDA(ks)
    td.wfnsym = row["target_irrep"]
    if abs(row["target_ss"] - 2.0) < 0.1 and mol.spin == 0:
        td.singlet = False
    td.nstates = max(6, 2 * rank + 2)
    td.verbose = 0
    td.kernel()
    per = perceive(syms, coords, include_sigma=False)
    an = analyse(ks, td, per.targets, n_states=rank,
                 rydberg_detectable=bool(rydberg_representable(ks)))
    narrowed = add_state_narrowed_tier(rec, mol, an, n_states, per.targets,
                                       perception=per, spin_2s=mol.spin)
    tier = rec.tiers[rec.recommended]
    idx = list(tier.orbital_indices)
    C = rec.mo_coeff[:, idx]
    nel = int(tier.n_electrons)
    info = {"pool_space": pool_space, "tier": rec.recommended, "narrowed": bool(narrowed),
            "native_space": [nel, len(idx)], "native_ncsf": ncsf(nel, len(idx)),
            "tda_states": [{"index": s.index, "ev": round(float(s.energy_ev), 3),
                            "character": s.character} for s in an.states[:rank]],
            "rydberg_detectable": bool(rydberg_representable(ks))}
    if capped:
        occ = [int(round(x)) for x in _occupancy(mol, mf, C)]
        ent = [float(rec.entropies[i - rec.ncore]) for i in idx]
        if ncsf(nel, len(idx)) > MAX_CSF:
            keep = cap_by_entropy(occ, ent)
            C = C[:, keep]
            nel = int(sum(occ[k] for k in keep))
            info["capped"] = True
        else:
            info["capped"] = False
        info["capped_space"] = [nel, C.shape[1]]
    info["seconds"] = round(time.time() - t0, 1)
    log(f"  engine pool {pool_space} -> {rec.recommended} {info['native_space']}"
        + (f" -> capped {info['capped_space']}" if capped else "")
        + f"  TDA: " + ", ".join(f"{s['ev']} {s['character']}" for s in info["tda_states"]))
    return C, nel, info


def symmetrise_active(mol, mf, C_act):
    """Nearest irrep-closed space to C_act, and the core/virtual around it.

    Each irrep's S-orthonormal symmetry orbitals are projected onto the
    active span. Every (irrep, direction, singular value) is pooled, the top
    ncas kept. A span that was already closed keeps all its directions at
    singular value 1. One that mixed irreps, such as formaldehyde's oxygen
    lone-pair hybrid (98% B2, 20% A1), keeps its dominant direction.

    The core is then, irrep by irrep, the doubly occupied space with the
    active directions projected out; the active electron count is whatever
    that leaves, and is reported rather than assumed, because replacing a
    hybrid with a pure direction can change it.

    Returns mo (core | active | virtual, every column in one irrep), ncore,
    n_active_electrons, and a report.
    """
    S = mol.intor_symmetric("int1e_ovlp")
    ncas = C_act.shape[1]
    occ = np.asarray(mf.mo_occ)
    picks = []
    sos = []
    for ir, so in zip(mol.irrep_id, mol.symm_orb):
        w, v = np.linalg.eigh(so.T @ S @ so)
        so = so @ v @ np.diag(w ** -0.5) @ v.T
        sos.append((ir, so))
        M = so.T @ S @ C_act
        u, sv, _ = np.linalg.svd(M, full_matrices=False)
        for k, x in enumerate(sv):
            picks.append((float(x), int(ir), so @ u[:, k]))
    picks.sort(key=lambda t: -t[0])
    kept, dropped = picks[:ncas], picks[ncas:]
    report = {"min_kept_sv": round(kept[-1][0], 4) if kept else None,
              "max_dropped_sv": round(dropped[0][0], 4) if dropped else 0.0,
              "was_closed": bool(kept and kept[-1][0] > 0.999
                                 and (not dropped or dropped[0][0] < 1e-3))}
    act_by_ir = {}
    for x, ir, vec in kept:
        act_by_ir.setdefault(ir, []).append(vec)
    core, act, virt = [], [], []
    n_act_el = 0.0
    frac_el, somo_out = [], 0.0
    for ir, so in sos:
        A = np.array(act_by_ir.get(ir, [])).T.reshape(mol.nao, -1)
        # occupied MOs of this irrep (mf is symmetry-adapted)
        mo_ir = [k for k in range(mf.mo_coeff.shape[1])
                 if abs(np.linalg.norm(so.T @ S @ mf.mo_coeff[:, k]) - 1) < 1e-6]
        D = mf.mo_coeff[:, [k for k in mo_ir if occ[k] == 2]]
        Sg = mf.mo_coeff[:, [k for k in mo_ir if occ[k] == 1]]
        # project active out of the doubly occupied space
        P = A @ A.T @ S if A.size else np.zeros((mol.nao, mol.nao))
        Dr = D - P @ D
        if Dr.size:
            u, sv, _ = np.linalg.svd(Dr.T @ S @ Dr)
            nc = int(np.sum(sv > 0.5))
            Q = Dr @ u[:, :nc] @ np.diag(sv[:nc] ** -0.5)
        else:
            nc, Q = 0, np.zeros((mol.nao, 0))
        n_act_el += 2 * (D.shape[1] - nc) + Sg.shape[1]
        # How integral that count really is: twice the docc weight inside the
        # active span plus the SOMO weight, against the integer used.
        if A.size:
            frac_el.append((2 * float(np.trace(D.T @ S @ P @ D)) if D.size else 0.0)
                           + (float(np.trace(Sg.T @ S @ P @ Sg)) if Sg.size else 0.0))
            somo_out += (Sg.shape[1] - float(np.trace(Sg.T @ S @ P @ Sg))) if Sg.size else 0.0
        else:
            somo_out += Sg.shape[1]
        # The virtual space is built inside this irrep's MOs rather than its
        # symmetry orbitals: an SCF that removed a near-linear dependency
        # (diacetylene in aug-cc-pVTZ keeps 229 of 230) has fewer MOs than
        # AOs, and the dropped direction must not come back as a virtual.
        M_ir = mf.mo_coeff[:, mo_ir]
        rest = M_ir - (P @ M_ir if A.size else 0) - Q @ Q.T @ S @ M_ir
        u, sv, _ = np.linalg.svd(rest.T @ S @ rest)
        nv = len(mo_ir) - nc - A.shape[1]
        V = rest @ u[:, :nv] @ np.diag(sv[:nv] ** -0.5) if nv > 0 else np.zeros((mol.nao, 0))
        core.append(Q)
        act.append(A)
        virt.append(V)
    core = np.hstack(core)
    act = np.hstack(act)
    virt = np.hstack(virt)
    mo = np.hstack([core, act, virt])
    ortho = float(np.abs(mo.T @ S @ mo - np.eye(mo.shape[1])).max())
    report["orthonormality_error"] = ortho
    report["active_electrons_fractional"] = round(sum(frac_el), 4)
    # A singly occupied orbital left outside the space would put an unpaired
    # electron in the core, which no closed core can hold.
    report["somo_weight_outside_active"] = round(somo_out, 4)
    return mo, core.shape[1], int(round(n_act_el)), report


# ------------------------------------------------------------ state average

def groups(states):
    """[(irrep, ss, nroots, [indices])] in first-appearance order.

    King's average is the ground state plus the states of the target's irrep
    and spin. Where those differ from the ground state's, one CI solver
    cannot hold both: a solver targets one irrep and one multiplicity. So the
    average is a mix of solvers, one per (irrep, spin) group, each solving
    for as many roots as the group has.
    """
    out = []
    for i, s in enumerate(states):
        for g in out:
            if g[0] == s["sym"] and abs(g[1] - s["ss"]) < 0.1:
                g[2] += 1
                g[3].append(i)
                break
        else:
            out.append([s["sym"], s["ss"], 1, [i]])
    return out


def nelec_for(total: int, ss: float):
    """Highest Ms for the state's spin, as King's tests do."""
    smult = SS_TO_SMULT[round(float(ss), 2)]
    two_ms = smult - 1
    na, nb = total // 2 + total % 2, total // 2
    while na - nb < two_ms:
        na += 1
        nb -= 1
    return (na, nb)


def make_solvers(mol, states, nel_tot):
    from pyscf.csf_fci import csf_solver
    solvers = []
    for irrep, ss, n, idx in groups(states):
        smult = SS_TO_SMULT[round(float(ss), 2)]
        s = csf_solver(mol, smult=smult, symm=True)
        s.wfnsym = irrep
        s.nroots = n
        s.spin = smult - 1
        s.nelec = nelec_for(nel_tot, ss)
        # The CSF solver keeps its own 4000 MB budget and compares it with
        # the process's whole resident size, so an aug-cc-pVTZ job that is
        # already past 4 GB fails building even a tiny spin-coupling matrix
        # (allyl: 0.004 MB asked, "-481 MB remaining").
        s.max_memory = mol.max_memory
        solvers.append((s, idx))
    return solvers


def sa_casscf(mf, mol, mo, ncore, ncas, nel_tot, states, solver=None, log=print):
    """SA-CASSCF over King's composition, equal weights, symmetry on.

    Returns (mc, per-state list in King's state order). The per-state list
    carries the CASSCF energy, the CI vector and the electron split, so that
    MC-PDFT and NEVPT2 can be run state by state exactly as King's tests do.
    """
    from pyscf import mcscf
    solver = solver or {}
    nst = len(states)
    w = [1.0 / nst] * nst
    mc = mcscf.CASSCF(mf, ncas, nel_tot)
    mc.ncore = ncore
    solvers = make_solvers(mol, states, nel_tot)
    if len(solvers) == 1:
        s, _ = solvers[0]
        mc.fcisolver = s
        mc.nelecas = s.nelec
        mc = mc.state_average_(w)
    else:
        mc = mcscf.addons.state_average_mix_(mc, [s for s, _ in solvers], w)
    mc.conv_tol = float(solver.get("conv_tol") or 1e-7)
    if solver.get("conv_tol_grad"):
        mc.conv_tol_grad = float(solver["conv_tol_grad"])
    mc.max_cycle_macro = int(solver.get("max_cycle_macro") or 1000)
    mc.max_cycle_micro = int(solver.get("max_cycle_micro") or 4)
    if solver.get("ah_level_shift"):
        mc.ah_level_shift = float(solver["ah_level_shift"])
    if solver.get("max_stepsize"):
        mc.max_stepsize = float(solver["max_stepsize"])
    mc.verbose = int(os.environ.get("QUEST_MC_VERBOSE", "0"))
    t0 = time.time()
    mc.kernel(mo)
    log(f"  SA-CASSCF({sum(mc.nelecas)},{ncas}) {nst} states converged={mc.converged} "
        f"{time.time() - t0:.1f}s")
    per = per_state(mc, solvers, states)
    return mc, per


def per_state(mc, solvers, states):
    """Map the solver-ordered roots back onto King's state order."""
    e = list(np.ravel(mc.e_states))
    ci = mc.ci if isinstance(mc.ci, (list, tuple)) else [mc.ci]
    out = [None] * len(states)
    k = 0
    for s, idx in solvers:
        # Within a group the solver returns roots in ascending energy, and
        # King's composition lists a group's states in the same order.
        for j, i in enumerate(idx):
            out[i] = {"e_casscf": float(e[k]), "ci": ci[k], "nelec": tuple(s.nelec),
                      "sym": states[i]["sym"], "ss": states[i]["ss"], "solver": s}
            k += 1
    return out


# ---------------------------------------------------------------- downstream

def dominant_open_shells(ci, ncas, nelec) -> int:
    """Number of singly occupied orbitals in the state's largest determinant."""
    from pyscf.fci import cistring
    ci = np.asarray(ci)
    na, nb = nelec
    ia, ib = np.unravel_index(int(np.argmax(np.abs(ci))), ci.shape)
    sa = int(cistring.addr2str(ncas, na, int(ia)))
    sb = int(cistring.addr2str(ncas, nb, int(ib)))
    return bin(sa ^ sb).count("1")


def m_diagnostic(rdm1_act, n_elec, n_open):
    """Tishchenko, Zheng and Truhlar's M diagnostic (JCTC 2008, 4, 1208).

    M = 1/2 [ 2 - n(MCDONO) + sum_SOMO |n_j - 1| + n(MCUNO) ], with n the
    natural-orbital occupation numbers of the state's own one-particle density
    matrix. "Doubly occupied", "singly occupied" and "unoccupied" refer to the
    state's dominant configuration. MCDONO is the least occupied of the doubly
    occupied natural orbitals, MCUNO the most occupied of the unoccupied ones.
    Definition as written out in Hoyer et al., PCCP 2017, citing the original.

    The dominant configuration's open shells are counted from its largest
    determinant, not from Ms: an open-shell singlet such as water's n -> 3s
    state has Ms = 0 and two singly occupied orbitals, and treating it as
    closed-shell put both of them into the doubly occupied and unoccupied
    sets and returned M = 0.998 for a state whose orbitals are each about
    half filled exactly as its configuration says. With the occupations
    sorted in descending order, the dominant configuration has
    (n_elec - n_open) / 2 doubly occupied orbitals, then n_open singly
    occupied, then the rest.
    """
    n = np.sort(np.linalg.eigvalsh(rdm1_act))[::-1]
    ndo = (int(n_elec) - int(n_open)) // 2
    do = n[:ndo]
    so = n[ndo:ndo + n_open]
    un = n[ndo + n_open:]
    mcdono = float(do.min()) if do.size else 2.0
    mcuno = float(un.max()) if un.size else 0.0
    return 0.5 * (2.0 - mcdono + float(np.sum(np.abs(so - 1.0))) + mcuno)


def downstream(mf, mc, per, grid_level=3, otfnal="tPBE", do_nevpt2=True, log=print):
    """tPBE and SC-NEVPT2 per state on the converged SA-CASSCF orbitals."""
    from pyscf import mcpdft, mcscf, mrpt
    mo = mc.mo_coeff
    ncas = mc.ncas
    for i, p in enumerate(per):
        t0 = time.time()
        pd = mcpdft.CASCI(mf, otfnal, ncas, p["nelec"], grids_level=grid_level)
        pd.mo_coeff = mo
        dec = pd.get_energy_decomposition(mo_coeff=mo, ci=p["ci"])
        p["e_tpbe"] = float(sum(float(np.ravel(x)[0]) for x in dec[:5]))
        p["e_tpbe0"] = 0.75 * p["e_tpbe"] + 0.25 * p["e_casscf"]
        c2 = mcscf.CASCI(mf, ncas, p["nelec"])
        c2.mo_coeff = mo
        c2.ci = p["ci"]
        dm1a, dm1b = c2.fcisolver.make_rdm1s(p["ci"], ncas, p["nelec"])
        p["n_open"] = dominant_open_shells(p["ci"], ncas, p["nelec"])
        p["m_diag"] = m_diagnostic(dm1a + dm1b, sum(p["nelec"]), p["n_open"])
        if do_nevpt2:
            p["e_nevpt2"] = p["e_casscf"] + float(mrpt.NEVPT(c2).kernel())
        p["seconds_downstream"] = round(time.time() - t0, 1)
    log("  downstream done: " + ", ".join(
        f"{p['sym']}/{p['ss']:.2f} tPBE {p['e_tpbe']:.6f}" for p in per))
    return per


# ------------------------------------------------------------ representable

def _string_irreps(norb, nel, orbsym):
    """Histogram of the irreps of all occupation strings (XOR of orbital ids)."""
    from itertools import combinations
    from collections import Counter
    c = Counter()
    for occ in combinations(range(norb), nel):
        ir = 0
        for k in occ:
            ir ^= int(orbsym[k])
        c[ir] += 1
    return c


def n_csf_irrep(norb, nel, two_s, irrep, orbsym):
    """CSFs of total spin S = two_s/2 and spatial irrep `irrep` in the space.

    D(Ms) counts determinants of the irrep at Ms; the spin-S CSFs number
    D(Ms=S) - D(Ms=S+1), since the lowering operator maps the second onto
    the first without changing spatial symmetry. Irrep ids are PySCF's,
    whose direct product in D2h and its subgroups is XOR.
    """
    def dets(two_ms):
        na = (nel + two_ms) // 2
        nb = nel - na
        if na > norb or nb < 0 or (nel + two_ms) % 2:
            return 0
        ca = _string_irreps(norb, na, orbsym)
        cb = _string_irreps(norb, nb, orbsym)
        return sum(ca[a] * cb[b] for a in ca for b in cb if (a ^ b) == irrep)
    return dets(two_s) - dets(two_s + 2)


def representable(mol, mo, ncore, ncas, nel_act, states):
    """Can this space hold every state of the average at all?

    BeH's engine space (1,1) holds one configuration and no excited state;
    CH's (1,2) has no A1 excited configuration. A state average asked for
    something the space cannot contain fails in the CI solver or, worse,
    returns the wrong state, so it is checked before any CASSCF and recorded
    as its own failure class.
    """
    from pyscf import symm
    orbsym = symm.label_orb_symm(mol, mol.irrep_id, mol.symm_orb,
                                 mo[:, ncore:ncore + ncas], check=False)
    need = {}
    for irrep, ss, n, _ in groups(states):
        need[(irrep, ss)] = n
    have = {}
    for (irrep, ss), n in need.items():
        two_s = SS_TO_SMULT[round(float(ss), 2)] - 1
        ir = symm.irrep_name2id(mol.groupname, irrep)
        have[f"{irrep}/{ss}"] = n_csf_irrep(ncas, nel_act, two_s, ir, orbsym)
    ok = all(have[f"{irrep}/{ss}"] >= n for (irrep, ss), n in need.items())
    return ok, have


# ---------------------------------------------------------------- scoring

def pick_states(per, row):
    """Ground and scored state, by King's rule.

    King et al. compare "the state highest in energy as judged by tPBE" of
    the target's irrep and spin with the TBE, and their shipped example takes
    the lowest-tPBE state of the ground state's group as the ground state.
    Within a group the CI solver returns roots in CASSCF order, which is not
    always tPBE order: acrolein's four-state A' average has its highest
    CASSCF root (8.38 eV) at the lowest tPBE (5.94 eV). So the states are
    chosen by tPBE, and the CASSCF-order choice is recorded beside it.
    """
    gs_key = (per[0]["sym"], per[0]["ss"])
    tg_key = (per[row["target_index"]]["sym"], per[row["target_index"]]["ss"])
    gs_idx = [i for i, p in enumerate(per) if (p["sym"], p["ss"]) == gs_key]
    tg_idx = [i for i, p in enumerate(per) if (p["sym"], p["ss"]) == tg_key]
    if gs_key == tg_key:
        g = min(gs_idx, key=lambda i: per[i]["e_tpbe"])
        t = max((i for i in tg_idx if i != g), key=lambda i: per[i]["e_tpbe"])
    else:
        g = min(gs_idx, key=lambda i: per[i]["e_tpbe"])
        t = max(tg_idx, key=lambda i: per[i]["e_tpbe"])
    return per[g], per[t], {"ground_index": g, "target_index": t,
                            "casscf_order_target_index": row["target_index"],
                            "rule": "King: highest tPBE of the target group"}


# ---------------------------------------------------------------- one row

NATIVE_MAX_CSF = 1_000_000   # harness feasibility bound for native spaces


def run_row(row, mode, log=print):
    from pyscf import lib
    t_all = time.time()
    out = {"name": row["name"], "mode": mode, "tbe_ev": row["tbe_ev"],
           "threads": lib.num_threads(), "host_load": os.getloadavg()[0]}
    mol = build_mol(row)
    out["nao"] = mol.nao
    mf, out["scf"] = reference_scf(mol, row, log=log)
    t0 = time.time()
    if mode == "apc2":
        C, nel_sel, out["selection"] = select_apc2(mf, mol, log=log)
        out["selection"].pop("entropies", None)
    else:
        C, nel_sel, out["selection"] = select_engine(mf, mol, row,
                                                     capped=(mode == "engine_capped"), log=log)
    out["seconds_selection"] = round(time.time() - t0, 1)
    out["selected_space"] = [nel_sel, C.shape[1]]
    mo, ncore, nel_act, srep = symmetrise_active(mol, mf, C)
    ncas = C.shape[1]
    out["symmetrisation"] = srep
    out["space"] = [nel_act, ncas]
    out["ncsf"] = ncsf(nel_act, ncas)
    out["electron_count_changed"] = nel_act != nel_sel
    if nel_act + 2 * ncore != mol.nelectron or srep["somo_weight_outside_active"] > 0.5:
        out["status"] = "inconsistent_space"
        return out
    if out["ncsf"] > NATIVE_MAX_CSF:
        out["status"] = "too_large"
        return out
    ok, have = representable(mol, mo, ncore, ncas, nel_act, row["states"])
    out["csf_per_group"] = have
    if not ok:
        out["status"] = "unrepresentable"
        return out
    states = row["states"]
    solver = row.get("solver") or {}
    t0 = time.time()
    mc, per = sa_casscf(mf, mol, mo, ncore, ncas, nel_act, states, solver=solver, log=log)
    out["converged"] = bool(mc.converged)
    out["seconds_casscf"] = round(time.time() - t0, 1)
    t0 = time.time()
    per = downstream(mf, mc, per, grid_level=int(solver.get("grid_level") or 3),
                     otfnal=solver.get("otfnal") or "tPBE", log=log)
    out["seconds_downstream"] = round(time.time() - t0, 1)
    gs, tg, out["scoring"] = pick_states(per, row)
    out["states"] = [{k: (v if not isinstance(v, np.generic) else v.item())
                      for k, v in p.items() if k not in ("ci", "solver")} for p in per]
    ex = {}
    for m in ("casscf", "tpbe", "tpbe0", "nevpt2"):
        ex[m] = round((tg[f"e_{m}"] - gs[f"e_{m}"]) * HARTREE_TO_EV, 4)
    out["excitation_ev"] = ex
    out["error_ev"] = {m: round(v - row["tbe_ev"], 4) for m, v in ex.items()}
    out["m_max"] = round(max(gs["m_diag"], tg["m_diag"]), 4)
    out["good_space"] = abs(out["error_ev"]["casscf"]) < GOOD_SPACE_EV
    out["status"] = "ok" if out["converged"] else "not_converged"
    out["seconds_total"] = round(time.time() - t_all, 1)
    return out


# --------------------------------------------------------------------- CLI

def load_manifest():
    return json.load(open(CACHE / "manifest.json"))


def row_by_name(name):
    for r in load_manifest()["rows"]:
        if r["name"] == name:
            return r
    raise KeyError(name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("one")
    one.add_argument("name")
    one.add_argument("mode", choices=["apc2", "engine", "engine_capped"])
    one.add_argument("--out", help="append the JSON result line to this file")
    a = ap.parse_args(argv)
    row = row_by_name(a.name)
    try:
        res = run_row(row, a.mode, log=lambda m: print(m, file=sys.stderr, flush=True))
    except Exception as exc:                                    # noqa: BLE001
        res = {"name": a.name, "mode": a.mode, "status": "error",
               "error": f"{type(exc).__name__}: {exc}",
               "traceback": traceback.format_exc()[-3000:]}
    line = json.dumps(res, default=float)
    print(line, flush=True)
    if a.out:
        with open(a.out, "a") as fh:
            fh.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
