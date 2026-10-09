#!/usr/bin/env python3
"""Aggregate a QUESTDB benchmark run into tables, and check them.

    python3 scripts/casbench/quest_report.py --run main            # print tables (markdown)
    python3 scripts/casbench/quest_report.py --run main --json out.json
    python3 scripts/casbench/quest_report.py --run main --check    # recompute independently

What every number means, so a table can be read without this file:

- A row is one (excitation, mode). Modes: `apc2` (King's selector rerun
  here), `engine` (the NexusQC engine's space for that state), `engine_capped`
  (the engine's space cut to King's max(12,12) budget by lowest APC-2-style
  entropy). An `engine_capped` row recorded as `alias` had an engine space
  already within the cap and is the engine row itself.
- Excitation energy: the scored state minus the ground state, both from the
  same state average, in eV. Error: computed minus QUESTDB TBE.
- Good space: |SA-CASSCF error| < 1.1 eV, King's filter.
- Denominators. `scored` counts rows that produced energies (ok and
  not_converged). Rows that could not be run are counted by status, never
  dropped silently: unrepresentable (the space cannot hold a state of the
  averaged irrep and spin), too_large (more than 1e6 CSFs), failed (two
  attempts without a result). The good-space fraction is over ALL 542
  excitations, counting every row that did not produce a good space as not
  good, exactly as King's 436/542 is.
- Error statistics are given three ways: over each mode's own good rows
  (King's convention), over the rows good in BOTH modes being compared (so a
  stricter filter cannot buy a lower error), and over all scored rows.
- The `king` columns are King et al.'s own Aug(12,12) numbers from their
  Zenodo record, for the same excitations.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / ".cache" / "casbench_quest"
METHODS = ("casscf", "tpbe", "tpbe0", "nevpt2")
KING_KEY = {"casscf": "CASSCF", "tpbe": "tPBE", "tpbe0": "tPBE0", "nevpt2": "NEVPT2"}
GOOD = 1.1


def load(run):
    man = {r["name"]: r for r in json.load(open(CACHE / "manifest.json"))["rows"]}
    res = {}
    for l in open(CACHE / "run" / run / "results.jsonl"):
        l = l.strip()
        if not l.startswith("{"):
            continue
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        if r.get("status") in (None, "error"):
            continue
        if r.get("states") and "scoring" not in r:
            r = rescore(r, man[r["name"]])
        res[(r["name"], r["mode"])] = r
    # resolve aliases
    for (n, m), r in list(res.items()):
        if r["status"] == "alias":
            base = res.get((n, r["alias_of"]))
            if base:
                res[(n, m)] = {**base, "mode": m, "alias_of": r["alias_of"]}
    return man, res


def rescore(r, row):
    """Apply King's state choice to a row written before the harness used it.

    Rows from the first calibration batch picked the target as the last root
    of its group in CASSCF order. The stored per-state energies are enough to
    redo it by King's rule (highest tPBE of the target group, lowest tPBE of
    the ground group), so those rows are re-scored here rather than rerun.
    """
    per = r["states"]
    H = 27.211386245988
    gk = (per[0]["sym"], per[0]["ss"])
    ti = row["target_index"]
    tk = (per[ti]["sym"], per[ti]["ss"])
    gi = [i for i, p in enumerate(per) if (p["sym"], p["ss"]) == gk]
    g = min(gi, key=lambda i: per[i]["e_tpbe"])
    t = max((i for i, p in enumerate(per) if (p["sym"], p["ss"]) == tk and i != g),
            key=lambda i: per[i]["e_tpbe"])
    ex = {m: (None if per[t].get(f"e_{m}") is None or per[g].get(f"e_{m}") is None
              else (per[t][f"e_{m}"] - per[g][f"e_{m}"]) * H) for m in METHODS}
    err = {m: (None if v is None else v - row["tbe_ev"]) for m, v in ex.items()}
    return {**r, "excitation_ev": ex, "error_ev": err,
            "good_space": abs(err["casscf"]) < GOOD,
            "scoring": {"ground_index": g, "target_index": t, "rescored": True}}


def stats(errs):
    if not errs:
        return None
    n = len(errs)
    return {"n": n, "mae": sum(abs(e) for e in errs) / n, "mse": sum(errs) / n,
            "rmse": math.sqrt(sum(e * e for e in errs) / n), "max": max(abs(e) for e in errs)}


def king_row(man_row):
    k = man_row["king"]["Aug1212"]
    if k.get("CASSCF") is None:
        return None
    err = {m: k[KING_KEY[m]] - man_row["tbe_ev"] for m in METHODS}
    return {"error_ev": err, "good_space": abs(err["casscf"]) < GOOD, "status": "ok"}


def category(r):
    c = r["category"]
    out = [f"mult{c['spin_mult']}"]
    if c["vr"]:
        out.append({"V": "valence", "R": "Rydberg", "CT": "CT"}[c["vr"]])
    if c["double"]:
        out.append("double")
    if c["type"] in ("npi",):
        out.append("n-pi*")
    if c["type"] in ("ppi",):
        out.append("pi-pi*")
    return out


def table(man, res, modes, subset=None, label="all"):
    names = [n for n in man if subset is None or subset(man[n])]
    lines = []
    srcs = {m: {n: res.get((n, m)) for n in names} for m in modes}
    srcs["king"] = {n: king_row(man[n]) for n in names}
    order = list(modes) + ["king"]
    lines.append(f"\n#### {label}: {len(names)} excitations\n")
    lines.append("| selector | good space | scored | not converged | unrepresentable | too large | failed | missing |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for m in order:
        rows = srcs[m]
        st = {}
        for n in names:
            r = rows[n]
            s = "missing" if r is None else r["status"]
            st[s] = st.get(s, 0) + 1
        good = sum(1 for r in rows.values() if r and r.get("good_space"))
        scored = st.get("ok", 0) + st.get("not_converged", 0)
        lines.append(f"| {m} | {good}/{len(names)} ({100 * good / max(1, len(names)):.0f}%) | {scored} | "
                     f"{st.get('not_converged', 0)} | {st.get('unrepresentable', 0)} | "
                     f"{st.get('too_large', 0)} | {st.get('failed', 0)} | {st.get('missing', 0)} |")
    lines.append("\nMAE / MSE / RMSE (eV) over each selector's own good rows:\n")
    lines.append("| selector | n | " + " | ".join(METHODS) + " |")
    lines.append("|---|---|" + "---|" * len(METHODS))
    for m in order:
        good = [r for r in srcs[m].values() if r and r.get("good_space")]
        cells = []
        for meth in METHODS:
            s = stats([r["error_ev"][meth] for r in good
                       if r["error_ev"].get(meth) is not None])
            cells.append("-" if not s else f"{s['mae']:.2f} / {s['mse']:+.2f} / {s['rmse']:.2f}")
        lines.append(f"| {m} | {len(good)} | " + " | ".join(cells) + " |")
    lines.append("\nMAE (eV) over the rows good for BOTH selectors in each pair:\n")
    lines.append("| pair | n | " + " | ".join(f"{x} (a, b)" for x in METHODS) + " |")
    lines.append("|---|---|" + "---|" * len(METHODS))
    for a in order:
        for b in order:
            if order.index(b) <= order.index(a):
                continue
            both = [n for n in names if srcs[a][n] and srcs[b][n]
                    and srcs[a][n].get("good_space") and srcs[b][n].get("good_space")]
            cells = []
            for meth in METHODS:
                bm = [n for n in both if srcs[a][n]["error_ev"].get(meth) is not None
                      and srcs[b][n]["error_ev"].get(meth) is not None]
                sa = stats([srcs[a][n]["error_ev"][meth] for n in bm])
                sb = stats([srcs[b][n]["error_ev"][meth] for n in bm])
                cells.append("-" if not sa else f"{sa['mae']:.2f}, {sb['mae']:.2f}")
            lines.append(f"| {a} vs {b} | {len(both)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def report(run):
    man, res = load(run)
    modes = sorted({m for _, m in res}, key=lambda m: ("apc2", "engine", "engine_capped").index(m)
                   if m in ("apc2", "engine", "engine_capped") else 9)
    present = sorted({n for n, _ in res})
    out = [f"### Run `{run}`: {len(present)} excitations with at least one result\n"]
    sub = {n: man[n] for n in present}
    out.append(table(sub, res, modes, label="every excitation in the run"))
    for lab, f in [("singlet excitations", lambda r: r["category"]["spin_mult"] == 1),
                   ("triplet excitations", lambda r: r["category"]["spin_mult"] == 3),
                   ("doublet excitations", lambda r: r["category"]["spin_mult"] == 2),
                   ("valence", lambda r: r["category"]["vr"] == "V"),
                   ("Rydberg", lambda r: r["category"]["vr"] == "R"),
                   ("double excitations", lambda r: r["category"]["double"])]:
        if any(f(r) for r in sub.values()):
            out.append(table(sub, res, modes, subset=f, label=lab))
    # M_max split uses the apc2 wave functions, as King used his own
    mm = {n: (res.get((n, "apc2")) or {}).get("m_max") for n in present}
    if any(v is not None for v in mm.values()):
        out.append(table(sub, res, modes, subset=lambda r: (mm.get(r["name"]) or 0) > 0.14,
                         label="M_max > 0.14 (M from the apc2 wave functions)"))
    # control vs King, row by row
    diffs = []
    for n in present:
        r = res.get((n, "apc2"))
        k = man[n]["king"]["Aug1212"]
        if r and r.get("excitation_ev") and k.get("NEVPT2") is not None:
            diffs.append((n, r["space"], man[n]["king_aug_space"],
                          {m: (None if r["excitation_ev"].get(m) is None
                               else r["excitation_ev"][m] - k[KING_KEY[m]]) for m in METHODS}))
    if diffs:
        out.append("\n#### APC-2 control against King's own Aug(12,12) rows\n")
        same = [d for d in diffs if list(d[1]) == list(d[2] or [])]
        out.append(f"{len(diffs)} rows; {len(same)} chose King's exact space. "
                   "Differences (ours - King's, eV) where the space matched:\n")
        out.append("| excitation | space | " + " | ".join(METHODS) + " |")
        out.append("|---|---|" + "---|" * len(METHODS))
        for n, sp, ks, d in same:
            out.append(f"| {n} | {tuple(sp)} | " + " | ".join(
                "-" if d[m] is None else f"{d[m]:+.3f}" for m in METHODS) + " |")
    return "\n".join(out)


def check(run) -> int:
    """Recompute the headline counts with a separate, deliberately naive path."""
    man = {r["name"]: r for r in json.load(open(CACHE / "manifest.json"))["rows"]}
    last = {}
    for l in open(CACHE / "run" / run / "results.jsonl"):
        try:
            r = json.loads(l)
        except Exception:                                       # noqa: BLE001
            continue
        last[(r.get("name"), r.get("mode"))] = r
    good = {}
    for (n, m), r in last.items():
        if r.get("status") == "alias":
            r = last.get((n, r.get("alias_of")), {})
        if r.get("excitation_ev"):
            g = abs(r["excitation_ev"]["casscf"] - man[n]["tbe_ev"]) < GOOD
            good.setdefault(m, []).append(g)
    _, res = load(run)
    bad = 0
    for m, gs in good.items():
        a = sum(gs)
        b = sum(1 for (n, mm), r in res.items() if mm == m and r.get("good_space"))
        print(f"{m}: good spaces recomputed from energies {a}, from the report's path {b}"
              + ("" if a == b else "   <-- MISMATCH"))
        bad += a != b
    dup = {}
    for l in open(CACHE / "run" / run / "results.jsonl"):
        try:
            r = json.loads(l)
        except Exception:                                       # noqa: BLE001
            continue
        if r.get("status") not in (None, "error"):
            k = (r["name"], r["mode"])
            dup[k] = dup.get(k, 0) + 1
    d = {k: v for k, v in dup.items() if v > 1}
    print(f"tasks with more than one final line: {len(d)}" + (f" {list(d)[:10]}" if d else ""))
    return 1 if (bad or d) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check(a.run)
    print(report(a.run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
