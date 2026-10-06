#!/usr/bin/env python3
"""Convert King et al.'s Zenodo wavefunction pickles into version-neutral files.

The pickles in Zenodo record 14889616 (King, Hermes, Truhlar, Gagliardi,
JCTC 2022, 18, 6065) were written with pandas 1.3.5 and PySCF 2.0, and
neither pandas 2 nor the PySCF this project pins can read them back: pandas
2 fails inside its block manager on the `energies` DataFrame. So they are read
once, in a side environment that has those old versions, and rewritten as a
JSON file (metadata and the per-state energy table) plus an `.npz` (the MO
coefficients and one CI vector per state). Everything downstream reads those.

Run with the side environment's interpreter, which `quest_fetch.py` creates:

    .cache/casbench_quest/env_pd13/bin/python scripts/casbench/quest_unpickle.py \\
        .cache/casbench_quest/king/FINALIZED_DATA/Aug1212 \\
        .cache/casbench_quest/king_npz/Aug1212

Deliberately Python 3.9 compatible and free of project imports.
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np


def _plain(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def convert(src: Path, dst: Path) -> None:
    with open(src, "rb") as fh:
        d = pickle.load(fh)
    meta = {k: _plain(d["metadata"][k]) for k in d["metadata"].index}
    # geom is a list of (symbol, [x, y, z]) tuples
    meta["geom"] = [[str(s), [float(c) for c in xyz]] for s, xyz in d["metadata"]["geom"]]
    energies = []
    for _, row in d["energies"].iterrows():
        energies.append({k: _plain(row[k]) for k in d["energies"].columns})
    arrays = {"mo_coeff": np.asarray(d["mo_coeff"])}
    for i, ci in enumerate(d["ci"]):
        arrays[f"ci_{i}"] = np.asarray(ci)
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst.with_suffix(".npz"), **arrays)
    with open(dst.with_suffix(".json"), "w") as fh:
        json.dump({"name": src.stem, "metadata": meta, "energies": energies,
                   "extra_keys": sorted(k for k in d if k not in
                                        ("metadata", "energies", "ci", "mo_coeff"))},
                  fh, indent=1)


def main() -> int:
    src_dir, dst_dir = Path(sys.argv[1]), Path(sys.argv[2])
    done = bad = 0
    for p in sorted(src_dir.glob("*.pkl")):
        out = dst_dir / p.stem
        if out.with_suffix(".json").exists() and out.with_suffix(".npz").exists():
            done += 1
            continue
        try:
            convert(p, out)
            done += 1
        except Exception as exc:                                # noqa: BLE001
            bad += 1
            print(f"FAILED {p.name}: {type(exc).__name__}: {exc}")
    print(f"{src_dir.name}: {done} converted, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
