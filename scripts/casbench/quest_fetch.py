#!/usr/bin/env python3
"""Fetch the QUESTDB benchmark inputs and build the 542-row manifest.

The benchmark (docs/TRACKER.md, docs/casbench/questdb.md) is run on exactly the
excitations, geometries, basis and state averages King, Hermes, Truhlar and
Gagliardi used (JCTC 2022, 18, 6065). All of that is in their Zenodo record
14889616 (CC-BY 4.0), so this script takes it from there rather than from the
QUESTDB website, whose public snapshot lacks fifteen of the radical rows.

Nothing fetched here is committed. Everything lands in the gitignored
`.cache/casbench_quest/`, which is outside `data/` so the deployment backup
does not copy a 7 GB third-party archive:

    zenodo/compiled_data.tar.gz   the record's archive, pinned by sha256
    zenodo/jun-cc-pvtz.dat        King's jun-cc-pV(T+d)Z basis file
    env_pd13/                     side environment that can read the pickles
    king/FINALIZED_DATA/...       extracted pickles and result spreadsheets
    king_npz/<combo>/<name>.*     the pickles rewritten as JSON + npz
    king_results/<combo>.csv      the spreadsheets as CSV
    manifest.json                 one entry per excitation (built here)

Every step is idempotent and skipped when its output already exists, so the
script can be rerun after an interruption:

    python3 scripts/casbench/quest_fetch.py            # everything
    python3 scripts/casbench/quest_fetch.py --manifest # only rebuild the manifest

The archive is ~7.2 GB; at the 1.4 to 3 MB/s seen on this host the first
download takes about an hour.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / ".cache" / "casbench_quest"
RECORD = "14889616"
ARCHIVE_URL = f"https://zenodo.org/api/records/{RECORD}/files/compiled_data.tar.gz/content"
BASIS_URL = f"https://zenodo.org/api/records/{RECORD}/files/jun-cc-pvtz.dat/content"
ARCHIVE_BYTES = 7246269119

COMBOS = ["Aug1212", "Jun1212", "TZ1212", "DZ1212", "Jun1010", "Jun88"]
SIDE_ENV = CACHE / "env_pd13"


def sh(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def download():
    z = CACHE / "zenodo"
    z.mkdir(parents=True, exist_ok=True)
    arc = z / "compiled_data.tar.gz"
    if not (arc.exists() and arc.stat().st_size == ARCHIVE_BYTES):
        sh(["curl", "-sSL", "-C", "-", "--retry", "5", "-o", arc, ARCHIVE_URL])
    if arc.stat().st_size != ARCHIVE_BYTES:
        raise SystemExit(f"archive is {arc.stat().st_size} bytes, expected {ARCHIVE_BYTES}")
    if not (z / "jun-cc-pvtz.dat").exists():
        sh(["curl", "-sSL", "-o", z / "jun-cc-pvtz.dat", BASIS_URL])
    sumfile = z / "compiled_data.sha256"
    if not sumfile.exists():
        h = hashlib.sha256()
        with open(arc, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 24), b""):
                h.update(chunk)
        sumfile.write_text(f"{h.hexdigest()}  compiled_data.tar.gz\n")
    print("archive sha256", sumfile.read_text().split()[0])


def side_env():
    """The environment that can unpickle King's files.

    The recipe is the one that worked, in order; each step undoes something
    the previous one broke. pip's pyscf 2.0.1 pulls a numpy that breaks
    pandas 1.3's compiled extensions ("numpy.dtype size changed"), so numpy
    and scipy are re-pinned after it.
    """
    py = SIDE_ENV / "bin" / "python"
    if py.exists():
        return py
    sh(["conda", "create", "-y", "-q", "-p", SIDE_ENV, "-c", "conda-forge",
        "python=3.9", "pandas=1.3.5", "numpy=1.21"])
    sh([SIDE_ENV / "bin" / "pip", "install", "-q", "pyscf==2.0.1"])
    sh([SIDE_ENV / "bin" / "pip", "install", "-q", "numpy==1.21.6", "scipy<1.9",
        "openpyxl==3.0.10"])
    return py


def extract():
    king = CACHE / "king"
    king.mkdir(parents=True, exist_ok=True)
    want = [c for c in COMBOS if not (king / "FINALIZED_DATA" / c).exists()]
    if not (king / "FINALIZED_DATA" / "Results").exists():
        want += ["Results", "Tests"]
    if want:
        sh(["tar", "xzf", CACHE / "zenodo" / "compiled_data.tar.gz", "-C", king,
            "--wildcards"] + [f"FINALIZED_DATA/{w}/*" for w in want])


def convert(py):
    for c in COMBOS:
        sh([py, REPO / "scripts" / "casbench" / "quest_unpickle.py",
            CACHE / "king" / "FINALIZED_DATA" / c, CACHE / "king_npz" / c])
    out = CACHE / "king_results"
    out.mkdir(exist_ok=True)
    code = ("import sys, pandas as pd\n"
            "for f in sys.argv[2:]:\n"
            "    pd.read_excel(f).to_csv(sys.argv[1] + '/' + f.rsplit('/', 1)[1][:-5] + '.csv', index=False)\n")
    xl = sorted(str(p) for p in (CACHE / "king" / "FINALIZED_DATA" / "Results").glob("*.xlsx"))
    sh([py, "-c", code, out] + xl)


def our_irreps(rec, arr):
    """Each averaged state's irrep under THIS PySCF's axis convention.

    King's labels were assigned by PySCF 2.0, and PySCF has since changed how
    it orients a planar C2v molecule: water's n -> 3s Rydberg state, King's
    "B2", is "B1" here. Targeting King's label verbatim asks the CI solver for
    a different state entirely (14.3 eV instead of 7.8 eV for water-x1). So
    the label is re-derived from King's own wavefunction: his orbitals are
    labelled by irrep in our convention, and each state's CI vector is asked
    which irrep it belongs to. Measured, not mapped by rule, so it is right for
    D2h permutations as much as for the C2v swap that exposed it.
    """
    sys.path.insert(0, str(REPO / "scripts" / "casbench"))
    import quest_bench as qb
    from pyscf import fci, symm
    meta = rec["metadata"]
    row = {"geometry": meta["geom"], "geometry_unit": meta["unit"],
           "charge": meta["charge"], "spin": meta["hf_spin"],
           "symmetry": meta["hf_symmetry"],
           "symmetry_subgroup": meta["hf_symmetry_subgroup"], "solver": meta}
    mol = qb.build_mol(row)
    mo = arr["mo_coeff"]
    orbsym = symm.label_orb_symm(mol, mol.irrep_id, mol.symm_orb, mo, check=False)
    ncas = int(meta["ncas"])
    nel = int(sum(meta["nelecas"]))
    ncore = (mol.nelectron - nel) // 2
    act = np.asarray(orbsym[ncore:ncore + ncas])
    out = []
    for i, e in enumerate(rec["energies"]):
        ws = fci.addons.guess_wfnsym(arr[f"ci_{i}"], ncas, qb.nelec_for(nel, e["ss"]), act)
        out.append(symm.irrep_id2name(mol.groupname, ws))
    return out, mol.groupname


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def build_manifest():
    """One entry per excitation, everything the harness needs and nothing more.

    The state average is read from King's Aug1212 record for that excitation
    (irreps, spins and weights of every averaged state). Where Aug1212 did
    not converge and so has no record, the composition is taken from the
    first other combination that has one: it is the same set of states, only
    the basis or the size differs.

    The scored state follows King's rule: among the averaged states carrying
    the target's irrep and spin, the highest in energy. In the composition
    that is the last such state, and `target_rank` says how many states of
    that irrep and spin the average holds, which is what the harness asks
    the CI solver and the engine's TDA for.
    """
    res = {c: {r["Name"]: r for r in csv.DictReader(open(CACHE / "king_results" / f"{c}.csv"))}
           for c in COMBOS}
    extra = {r["Name"]: r for r in csv.DictReader(
        open(CACHE / "king_results" / "aug_ccpvtz_results.csv"))}
    names = list(res["Aug1212"])
    rows = []
    problems = []
    for name in names:
        src = None
        for c in COMBOS:
            p = CACHE / "king_npz" / c / f"{name}.json"
            if p.exists():
                src = (c, json.load(open(p)))
                break
        if src is None:
            problems.append(f"{name}: no record in any combination")
            continue
        combo, rec = src
        meta = rec["metadata"]
        arr = np.load(CACHE / "king_npz" / combo / f"{name}.npz")
        ours, group = our_irreps(rec, arr)
        states = [{"sym": o, "sym_king": e["sym"], "ss": round(float(e["ss"]), 2),
                   "weight": float(e["weight"])} for o, e in zip(ours, rec["energies"])]
        a = res["Aug1212"][name]
        # Two rows (pyridazine-x1, -x2) did not converge in Aug1212 and carry
        # no label there; every combination describes the same state.
        target_sym = next(res[c][name]["PySCF Sym"] for c in COMBOS
                          if res[c].get(name, {}).get("PySCF Sym"))
        target_ss = {"1": 0.0, "3": 2.0, "2": 0.75}[target_sym[0]]
        irrep = target_sym[1:]
        # The target is located with King's own labels, which are consistent
        # within his record; the harness then asks for it by our label.
        idx = [i for i, s in enumerate(states)
               if s["sym_king"] == irrep and abs(s["ss"] - target_ss) < 0.1]
        gs = states[0]
        if not idx or (idx == [0]):
            problems.append(f"{name}: target {target_sym} not in its own state average {states}")
            continue
        target_index = idx[-1]
        rank = len([i for i in idx if i != 0])
        irrep_king, irrep = irrep, states[target_index]["sym"]
        x = extra.get(name, {})
        aug_meta = None
        p = CACHE / "king_npz" / "Aug1212" / f"{name}.json"
        if p.exists():
            aug_meta = json.load(open(p))["metadata"]
        rows.append({
            "name": name,
            "molecule": name.rsplit("-x", 1)[0],
            "geometry_unit": meta["unit"],
            "geometry": meta["geom"],
            "charge": int(meta["charge"]),
            "spin": int(meta["hf_spin"]),
            "point_group": group,
            "symmetry": meta["hf_symmetry"],
            "symmetry_subgroup": meta.get("hf_symmetry_subgroup"),
            "states": states,
            "target_index": target_index,
            "target_irrep": irrep,
            "target_irrep_king": irrep_king,
            "target_ss": target_ss,
            "target_rank": rank,
            "target_shares_gs_irrep": irrep_king == gs["sym_king"] and abs(target_ss - gs["ss"]) < 0.1,
            "composition_from": combo,
            "tbe_ev": float(a["TBE"]),
            "qdb_sym": a["QDB Sym"],
            "pyscf_sym": target_sym,
            "category": {
                "spin_mult": {0.0: 1, 2.0: 3, 0.75: 2}[target_ss],
                "vr": x.get("V/R") or None,
                "type": (x.get("Type") or "").strip() or None,
                "safe": _f(x.get("Safe?")),
                "size": _f(x.get("Size")),
                "t1": _f(x.get("T1")),
                "tbe_method": x.get("Method") or None,
                "double": (x.get("Type") or "").strip() == "dou",
            },
            "king": {c: {m: _f(res[c].get(name, {}).get(m))
                         for m in ("CASSCF", "tPBE", "tPBE0", "NEVPT2")} for c in COMBOS},
            "king_aug_space": ([int(sum(aug_meta["nelecas"])), int(aug_meta["ncas"])]
                               if aug_meta else None),
            "solver": ({k: aug_meta[k] for k in (
                "conv_tol", "conv_tol_grad", "max_cycle_macro", "max_cycle_micro",
                "level_shift", "ah_level_shift", "max_stepsize", "grid_level", "otfnal",
                "basis")} if aug_meta else None),
            "flags": (["geometry_suspect_unit_conversion"]
                      if name.rsplit("-x", 1)[0] in ("vinyl", "con", "cno", "no") else []),
        })
    out = {"source": f"Zenodo record {RECORD}, King, Hermes, Truhlar, Gagliardi, "
                     f"JCTC 2022, 18, 6065 (CC-BY 4.0)",
           "archive_sha256": (CACHE / "zenodo" / "compiled_data.sha256").read_text().split()[0],
           "n": len(rows), "problems": problems, "rows": rows}
    with open(CACHE / "manifest.json", "w") as fh:
        json.dump(out, fh, indent=1)
    return out


def check(man) -> int:
    """Acceptance for P1.1: 542 rows, each with a geometry and a target irrep
    that resolves in PySCF for that molecule's point group."""
    from pyscf import gto, symm
    bad = list(man["problems"])
    for r in man["rows"]:
        if not r["geometry"]:
            bad.append(f"{r['name']}: no geometry")
            continue
        mol = gto.M(atom=[(s, xyz) for s, xyz in r["geometry"]], unit=r["geometry_unit"],
                    basis="sto-3g", charge=r["charge"], spin=r["spin"],
                    symmetry=r["symmetry"], symmetry_subgroup=r["symmetry_subgroup"],
                    verbose=0)
        if mol.groupname != r["point_group"]:
            bad.append(f"{r['name']}: point group {mol.groupname}, King's {r['point_group']}")
        for s in r["states"]:
            try:
                symm.irrep_name2id(mol.groupname, s["sym"])
            except Exception:                                   # noqa: BLE001
                bad.append(f"{r['name']}: irrep {s['sym']} not in {mol.groupname}")
    print(f"manifest: {man['n']} rows; {len(bad)} problem(s)")
    for b in bad:
        print("  ", b)
    return 0 if (man["n"] == 542 and not bad) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", action="store_true", help="only rebuild and check the manifest")
    a = ap.parse_args()
    if not a.manifest:
        download()
        py = side_env()
        extract()
        convert(py)
    return check(build_manifest())


if __name__ == "__main__":
    sys.exit(main())
