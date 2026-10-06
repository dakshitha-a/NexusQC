#!/usr/bin/env python3
"""Does our APC-2 control choose the active space King chose, row by row?

The cheapest validation of the control selector there is, and the first:
no CASSCF, only the reference SCF and the selection. King's Aug1212 record
for every excitation stores the active space his APC-2 selected, (nelecas,
ncas). If our reimplementation of his candidate preparation (23 + 23
Boys-localised orbitals per irrep) and PySCF's APC-2 give the same size on
the large majority of rows, the preparation is right; where they differ the
row is named. APC selects per molecule, not per excitation, so it runs once
per molecule and is compared with every one of that molecule's rows.

The reference SCF it computes is cached and reused by the benchmark itself.

    python3 scripts/casbench/quest_apc_sizes.py [--workers 10] [--threads 8]
    python3 scripts/casbench/quest_apc_sizes.py --one <molecule>     # worker

Results: .cache/casbench_quest/apc_sizes.jsonl (one line per molecule),
and a summary printed at the end.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / ".cache" / "casbench_quest"
OUT = CACHE / "apc_sizes.jsonl"


def one(molecule: str) -> int:
    sys.path.insert(0, str(REPO / "scripts" / "casbench"))
    import quest_bench as qb
    rows = [r for r in qb.load_manifest()["rows"] if r["molecule"] == molecule]
    r0 = rows[0]
    t0 = time.time()
    mol = qb.build_mol(r0)
    mf, info = qb.reference_scf(mol, r0, log=lambda m: None)
    C, nel, rep = qb.select_apc2(mf, mol, log=lambda m: None)
    rec = {"molecule": molecule, "nao": mol.nao, "ours": [nel, C.shape[1]],
           "scf": info, "seconds": round(time.time() - t0, 1),
           "rows": {r["name"]: r["king_aug_space"] for r in rows}}
    print(json.dumps(rec), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--one")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()
    if a.one:
        return one(a.one)
    sys.path.insert(0, str(REPO / "scripts" / "casbench"))
    import quest_bench as qb
    rows = qb.load_manifest()["rows"]
    mols = {}
    for r in rows:
        mols.setdefault(r["molecule"], len(r["geometry"]))
    done = set()
    if OUT.exists():
        done = {json.loads(l)["molecule"] for l in open(OUT) if l.strip()}
    todo = sorted((m for m in mols if m not in done), key=lambda m: -mols[m])
    env = dict(os.environ, OMP_NUM_THREADS=str(a.threads), MKL_NUM_THREADS=str(a.threads),
               PYTHONPATH=str(REPO))

    def run(m):
        p = subprocess.run([sys.executable, __file__, "--one", m], env=env,
                           capture_output=True, text=True)
        line = next((l for l in p.stdout.splitlines() if l.startswith("{")), None)
        if line is None:
            line = json.dumps({"molecule": m, "error": (p.stderr or "")[-800:]})
        with open(OUT, "a") as fh:
            fh.write(line + "\n")
        print(line[:160], flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(run, todo))
    return summary()


def summary() -> int:
    recs = [json.loads(l) for l in open(OUT) if l.strip()]
    match = miss = none = 0
    misses = []
    for r in recs:
        if "error" in r:
            print("ERROR", r["molecule"], r["error"][-300:])
            continue
        for name, king in r["rows"].items():
            if king is None:
                none += 1
            elif list(king) == list(r["ours"]):
                match += 1
            else:
                miss += 1
                misses.append((name, king, r["ours"]))
    print(f"\nrows whose APC-2 space matches King's exactly: {match}; differ: {miss}; "
          f"King has no Aug1212 record: {none}")
    for m in misses:
        print("   differs:", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
