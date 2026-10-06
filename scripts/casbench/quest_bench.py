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
    selector cannot win by starting from a different mean field. No density
    fitting: King ran without it, Phase 0 reproduced him without it, and
    PySCF has no JK fitting basis for beryllium, which three QUESTDB radicals
    contain. The converged orbitals are cached per molecule and basis.
    """
    from pyscf import scf
    from app.chemistry.cas.reference import stabilise
    key = f"{row['molecule']}_{row['charge']}_{row['spin']}_{mol.basis if isinstance(mol.basis, str) else 'custom'}"
    chk = CACHE / "scf" / f"{key}.npz"
    mf = scf.RHF(mol) if mol.spin == 0 else scf.ROHF(mol)
    mf.verbose = 0
    mf.conv_tol = 1e-10
    if cache and chk.exists():
        z = np.load(chk)
        dm = mf.make_rdm1(z["mo_coeff"], z["mo_occ"])
        mf.kernel(dm0=dm)
        return mf, {"cached": True, "energy": float(mf.e_tot),
                    "stabilised_shift_eh": float(z["shift"])}
    t0 = time.time()
    mf.kernel()
    e0 = float(mf.e_tot)
    stabilise(mf, check_external=False)
    shift = float(mf.e_tot) - e0
    info = {"cached": False, "energy": float(mf.e_tot), "stabilised_shift_eh": shift,
            "seconds": round(time.time() - t0, 1)}
    log(f"  SCF {mol.nao} AO  E={mf.e_tot:.8f}  stabilise moved it {shift:+.2e} Eh  "
        f"{info['seconds']}s")
    if cache:
        chk.parent.mkdir(parents=True, exist_ok=True)
        tmp = chk.with_suffix(".tmp.npz")
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
    ncas, nelecas, casorbs, active_idx = Chooser(
        orbs, occ_all, ent_all, max_size, verbose=0).kernel()
    nel = int(round(np.sum(nelecas))) if hasattr(nelecas, "__len__") else int(nelecas)
    log(f"  APC-2 picked ({nel},{ncas}) from {Cc.shape[1]} candidates")
    # `casorbs` is the whole reordered set (inactive | active | secondary);
    # the active columns are the ones the chooser kept.
    return orbs[:, list(active_idx)], nel, {"n_candidates": int(Cc.shape[1]),
                          "entropies": [float(x) for x in ent]}


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
        # SOMOs must be active for an open shell to make sense
        Csym = np.hstack([so])
        rest = Csym - (A @ A.T @ S @ Csym if A.size else 0) - Q @ Q.T @ S @ Csym
        u, sv, _ = np.linalg.svd(rest.T @ S @ rest)
        nv = so.shape[1] - nc - A.shape[1]
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
    mc.verbose = 0
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
    one.add_argument("--out")
    a = ap.parse_args(argv)
    raise SystemExit("not wired yet")


if __name__ == "__main__":
    sys.exit(main())
