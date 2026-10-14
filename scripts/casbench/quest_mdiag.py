#!/usr/bin/env python3
"""The M diagnostic of every QUESTDB excitation, from King's own wave functions.

    python3 scripts/casbench/quest_mdiag.py      # writes .cache/casbench_quest/king_m.json

King splits his results at M_max = max(M(ground), M(excited)) > 0.14, with
M computed from his Aug(12,12) wave functions. The main run stored an M per
row, but counted open shells from the largest determinant in the CASSCF
orbitals, which is basis-dependent and wrong for about a fifth of ground
states. The run did not keep its CI vectors, so its M cannot be redone. This
script computes M instead from King's CI vectors, cached by quest_fetch.py,
with the harness's corrected `dominant_open_shells`. The split is then the
same for all three modes, as it was for King.

The ground and target roots are picked by King's rule, the same as the
harness: lowest tPBE of the ground group, highest tPBE of the target group.

It refuses to write unless it reproduces King's published numbers: the 16
ground- and excited-state values in SI Table S12, to 0.006, and the quartiles
of M_max over his 436 good rows (SI Figure 20), to 0.01.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from quest_bench import dominant_open_shells, m_diagnostic  # noqa: E402
from quest_reproduce_king import nelecas_for  # noqa: E402

CACHE = HERE.parents[1] / ".cache" / "casbench_quest"
OUT = CACHE / "king_m.json"

# King et al., JCTC 2022, SI Table S12: (M(ground), M(excited)).
TABLE_S12 = {
    "cyclopentadienethione-x5": (0.14, 0.78), "cyclopentadienone-x4": (0.13, 0.65),
    "beryllium-x1": (0.12, 0.86), "cyclopentadienone-x9": (0.13, 0.16),
    "formaldehyde-x8": (0.07, 0.38), "cyclopentadienethione-x9": (0.15, 0.16),
    "cyclopentadienone-x3": (0.13, 0.17), "cyclopentadienethione-x3": (0.15, 0.14),
    "carbon_trimer-x2": (0.11, 0.82), "carbon_trimer-x1": (0.11, 0.73),
    "glyoxal-x3": (0.10, 0.52), "nitroxyl-x2": (0.09, 0.14),
    "benzoquinone-x3": (0.14, 0.96), "carbon_dimer-x1": (0.39, 0.16),
    "carbon_dimer-x2": (0.38, 0.27), "benzene-x7": (0.06, 0.42),
}
# SI Figure 20: quartiles of M_max over the 436 rows with |CASSCF - TBE| < 1.1 eV.
QUARTILES = (0.08, 0.11, 0.44)


def king_m(row) -> dict:
    from pyscf.fci import direct_spin1
    base = CACHE / "king_npz" / "Aug1212" / row["name"]
    d = json.load(open(base.with_suffix(".json")))
    a = np.load(base.with_suffix(".npz"))
    ncas = int(d["metadata"]["ncas"])
    total = int(sum(d["metadata"]["nelecas"]))
    E, st = d["energies"], row["states"]
    group = lambda i: (st[i]["sym"], st[i]["ss"])  # noqa: E731
    g = min((i for i in range(len(st)) if group(i) == group(0)), key=lambda i: E[i]["tPBE"])
    tk = group(row["target_index"])
    t = max((i for i in range(len(st)) if group(i) == tk and i != g), key=lambda i: E[i]["tPBE"])
    m = []
    for i in (g, t):
        nel = nelecas_for(total, E[i]["ss"])
        da, db = direct_spin1.make_rdm1s(a[f"ci_{i}"], ncas, nel)
        m.append(m_diagnostic(da + db, sum(nel), dominant_open_shells(a[f"ci_{i}"], ncas, nel, da + db)))
    return {"ground_index": g, "target_index": t, "m_gs": m[0], "m_es": m[1], "m_max": max(m)}


def main() -> int:
    rows = json.load(open(CACHE / "manifest.json"))["rows"]
    out = {}
    for r in rows:
        try:
            out[r["name"]] = king_m(r)
        except FileNotFoundError:
            out[r["name"]] = {"missing": "no Aug(12,12) record in King's data"}
    bad = 0
    for n, (g, e) in TABLE_S12.items():
        v = out[n]
        hit = abs(v["m_gs"] - g) < 0.006 and abs(v["m_es"] - e) < 0.006
        bad += not hit
        print(f"{n:26s} King {g:.2f} {e:.2f}  here {v['m_gs']:.2f} {v['m_es']:.2f}" + ("" if hit else "  <-- DIFF"))
    good = [out[r["name"]]["m_max"] for r in rows
            if r["king"]["Aug1212"].get("CASSCF") is not None
            and abs(r["king"]["Aug1212"]["CASSCF"] - r["tbe_ev"]) < 1.1 and "m_max" in out[r["name"]]]
    q = [float(np.percentile(good, p)) for p in (25, 50, 75)]
    qok = all(abs(x - y) < 0.01 for x, y in zip(q, QUARTILES))
    print(f"quartiles over {len(good)} good rows: {[round(x, 3) for x in q]} (King {QUARTILES})"
          + ("" if qok else "  <-- DIFF"))
    print(f"missing: {[n for n, v in out.items() if 'missing' in v]}")
    if bad or not qok:
        print("not written: King's published values are not reproduced")
        return 1
    OUT.write_text(json.dumps(out, indent=0))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
