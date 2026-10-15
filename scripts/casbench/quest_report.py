#!/usr/bin/env python3
"""Aggregate a QUESTDB benchmark run into tables, and check them.

    python3 scripts/casbench/quest_report.py --run main            # print tables (markdown)
    python3 scripts/casbench/quest_report.py --run main --write    # write docs/casbench/questdb.md
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
- Denominators. Every table counts all excitations of its category. `scored`
  counts rows that produced energies. Rows that did not are counted by
  status, never dropped silently: wall cap (SA-CASSCF still running at the
  48 h per-row cap), unrepresentable (the space cannot hold a state of the
  averaged irrep and spin), too large (more than 1e6 CSFs), declined (the
  engine perceived no targets and built no space), failed (two attempts
  without a result for any other reason). The good-space fraction counts
  every row that did not produce a good space as not good, exactly as
  King's 436/542 is.
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
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / ".cache" / "casbench_quest"
LEDGER = REPO / "docs" / "casbench" / "questdb.md"
METHODS = ("casscf", "tpbe", "tpbe0", "nevpt2")
KING_KEY = {"casscf": "CASSCF", "tpbe": "tPBE", "tpbe0": "tPBE0", "nevpt2": "NEVPT2"}
MODES = ("apc2", "engine", "engine_capped")
GOOD = 1.1
DECLINED = "No targets were perceived"
STATUSES = ("not_converged", "wall_cap", "unrepresentable", "too_large", "declined", "failed", "missing")


def load(run):
    man = {r["name"]: r for r in json.load(open(CACHE / "manifest.json"))["rows"]}
    res, last_error = {}, {}
    for l in open(CACHE / "run" / run / "results.jsonl"):
        l = l.strip()
        if not l.startswith("{"):
            continue
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        key = (r.get("name"), r.get("mode"))
        if r.get("status") == "error":
            last_error[key] = r.get("error") or ""
            continue
        if r.get("status") is None:
            continue
        if r.get("states") and "scoring" not in r:
            r = rescore(r, man[r["name"]])
        if r["status"] == "failed":
            cause = last_error.get(key, "")
            r = {**r, "cause": cause, "status": "declined" if DECLINED in cause else "failed"}
        if r["status"] == "not_converged" and r.get("wall_cap"):
            r = {**r, "status": "wall_cap"}
        res[key] = r
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
    err = {m: (None if k.get(KING_KEY[m]) is None else k[KING_KEY[m]] - man_row["tbe_ev"])
           for m in METHODS}
    return {"error_ev": err, "good_space": abs(err["casscf"]) < GOOD, "status": "ok",
            "space": man_row.get("king_aug_space")}


def scored(r):
    return bool(r and r.get("error_ev") and r["error_ev"].get("casscf") is not None)


def own_good_stats(rows, meth):
    """Error statistics over the rows a selector itself kept: King's convention."""
    return stats([r["error_ev"][meth] for r in rows.values()
                  if r and r.get("good_space") and r["error_ev"].get(meth) is not None])


def fmt(s):
    return "-" if not s else f"{s['mae']:.2f} / {s['mse']:+.2f} / {s['rmse']:.2f} / {s['max']:.2f}"


def king_m():
    """M_max per excitation from King's own wave functions (quest_mdiag.py)."""
    p = CACHE / "king_m.json"
    return {n: v.get("m_max") for n, v in json.load(open(p)).items()} if p.exists() else {}


def splits():
    km = king_m()
    out = [
        ("every excitation", lambda r: True),
        ("singlet excitations", lambda r: r["category"]["spin_mult"] == 1),
        ("triplet excitations", lambda r: r["category"]["spin_mult"] == 3),
        ("doublet excitations", lambda r: r["category"]["spin_mult"] == 2),
        ("valence", lambda r: r["category"]["vr"] == "V"),
        ("Rydberg", lambda r: r["category"]["vr"] == "R"),
        ("n-pi*", lambda r: r["category"]["type"] == "npi"),
        ("pi-pi*", lambda r: r["category"]["type"] == "ppi"),
        ("double excitations", lambda r: r["category"]["double"]),
    ]
    if km:
        out.append(("M_max > 0.14 (M from King's Aug(12,12) wave functions)",
                    lambda r: (km.get(r["name"]) or 0) > 0.14))
    return out


def numbers(man, res, modes, subset):
    """Every aggregate a table shows, as numbers, so --check can compare them."""
    names = [n for n in man if subset(man[n])]
    srcs = {m: {n: res.get((n, m)) for n in names} for m in modes}
    srcs["king"] = {n: king_row(man[n]) for n in names}
    order = list(modes) + ["king"]
    out = {"n": len(names), "names": names, "srcs": srcs, "order": order, "sel": {}, "pairs": {}}
    for m in order:
        rows = srcs[m]
        st = {}
        for n in names:
            s = "missing" if rows[n] is None else rows[n]["status"]
            st[s] = st.get(s, 0) + 1
        sc = [r for r in rows.values() if scored(r)]
        out["sel"][m] = {
            "good": sum(1 for r in rows.values() if r and r.get("good_space")),
            "scored": len(sc), "status": st,
            "own": {k: own_good_stats(rows, k) for k in METHODS},
            "all": {k: stats([r["error_ev"][k] for r in sc if r["error_ev"].get(k) is not None])
                    for k in METHODS}}
    for a in order:
        for b in order[order.index(a) + 1:]:
            both = [n for n in names if srcs[a][n] and srcs[b][n]
                    and srcs[a][n].get("good_space") and srcs[b][n].get("good_space")]
            cell = {"n": len(both)}
            for k in METHODS:
                bm = [n for n in both if srcs[a][n]["error_ev"].get(k) is not None
                      and srcs[b][n]["error_ev"].get(k) is not None]
                sa = stats([srcs[a][n]["error_ev"][k] for n in bm])
                sb = stats([srcs[b][n]["error_ev"][k] for n in bm])
                cell[k] = None if not sa else (sa["mae"], sb["mae"])
            out["pairs"][(a, b)] = cell
    return out


def table(man, res, modes, subset, label):
    N = numbers(man, res, modes, subset)
    lines = [f"\n#### {label}: {N['n']} excitations\n",
             "| selector | good space | scored | " + " | ".join(s.replace("_", " ") for s in STATUSES) + " |",
             "|---|---|---|" + "---|" * len(STATUSES)]
    for m in N["order"]:
        x = N["sel"][m]
        lines.append(f"| {m} | {x['good']}/{N['n']} ({100 * x['good'] / max(1, N['n']):.0f}%) | {x['scored']} | "
                     + " | ".join(str(x["status"].get(s, 0)) for s in STATUSES) + " |")
    lines += ["\nMAE / MSE / RMSE / max |error| (eV) over each selector's own good rows:\n",
              "| selector | n | " + " | ".join(METHODS) + " |", "|---|---|" + "---|" * len(METHODS)]
    for m in N["order"]:
        x = N["sel"][m]
        lines.append(f"| {m} | {x['good']} | " + " | ".join(fmt(x["own"][k]) for k in METHODS) + " |")
    lines += ["\nMAE (eV) over the rows good for BOTH selectors in each pair:\n",
              "| pair | n | " + " | ".join(f"{k} (a, b)" for k in METHODS) + " |",
              "|---|---|" + "---|" * len(METHODS)]
    for (a, b), c in N["pairs"].items():
        lines.append(f"| {a} vs {b} | {c['n']} | " + " | ".join(
            "-" if c[k] is None else f"{c[k][0]:.2f}, {c[k][1]:.2f}" for k in METHODS) + " |")
    lines += ["\nMAE / MSE / RMSE / max |error| (eV) over every scored row, no filter:\n",
              "| selector | n | " + " | ".join(METHODS) + " |", "|---|---|" + "---|" * len(METHODS)]
    for m in N["order"]:
        x = N["sel"][m]
        lines.append(f"| {m} | {x['scored']} | " + " | ".join(fmt(x["all"][k]) for k in METHODS) + " |")
    return "\n".join(lines)


def report(run):
    man, res = load(run)
    modes = [m for m in MODES if any(mm == m for _, mm in res)]
    out = [table(man, res, modes, f, lab) for lab, f in splits()
           if any(f(r) for r in man.values())]
    # control vs King, row by row
    diffs = []
    for n in man:
        r = res.get((n, "apc2"))
        k = man[n]["king"]["Aug1212"]
        if scored(r) and k.get("CASSCF") is not None:
            diffs.append((n, r["space"], man[n]["king_aug_space"],
                          {m: (None if r["excitation_ev"].get(m) is None or k.get(KING_KEY[m]) is None
                               else r["excitation_ev"][m] - k[KING_KEY[m]]) for m in METHODS}))
    if diffs:
        out.append("\n#### APC-2 control against King's own Aug(12,12) rows\n")
        same = [d for d in diffs if list(d[1]) == list(d[2] or [])]
        out.append(f"{len(diffs)} excitations scored by both; on {len(same)} the control chose "
                   "King's exact space. Over those, ours minus King's (eV):\n")
        out.append("| method | n | mean | mean abs | within 0.1 eV | max abs |")
        out.append("|---|---|---|---|---|---|")
        for m in METHODS:
            v = [d[3][m] for d in same if d[3][m] is not None]
            if v:
                out.append(f"| {m} | {len(v)} | {sum(v) / len(v):+.3f} | "
                           f"{sum(abs(x) for x in v) / len(v):.3f} | "
                           f"{sum(1 for x in v if abs(x) < 0.1)} | {max(abs(x) for x in v):.2f} |")
    return "\n".join(out), man, res, modes


def per_excitation(man, res, modes):
    lines = ["\n## Every excitation\n",
             "Errors are computed minus TBE, in eV. `space` is (electrons, orbitals). A dash "
             "means the row produced no number; the status column says why. NEVPT2 is not run "
             "above 24 active orbitals.\n",
             "| excitation | spin | V/R | TBE | " + " | ".join(
                 f"{m} space | {m} CASSCF | {m} tPBE0 | {m} NEVPT2 | {m} status" for m in modes)
             + " | King CASSCF | flags |",
             "|---|---|---|---|" + "---|" * (5 * len(modes)) + "---|---|"]
    for n, row in man.items():
        c = row["category"]
        cells = [n, str(c["spin_mult"]), c["vr"] or "-", f"{row['tbe_ev']:.2f}"]
        for m in modes:
            r = res.get((n, m))
            if r is None:
                cells += ["-", "-", "-", "-", "missing"]
                continue
            sp = r.get("space")
            cells.append(f"({sp[0]},{sp[1]})" if sp else "-")
            for meth in ("casscf", "tpbe0", "nevpt2"):
                v = (r.get("error_ev") or {}).get(meth)
                cells.append("-" if v is None else f"{v:+.2f}")
            st = r["status"] + (" (alias)" if r.get("alias_of") else "")
            cells.append(st + ("" if not scored(r) or r.get("good_space") else ", not good"))
        k = king_row(row)
        cells.append("-" if not k else f"{k['error_ev']['casscf']:+.2f}")
        cells.append(", ".join(row.get("flags") or []) or "-")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def provenance(run, res):
    cfg = json.load(open(CACHE / "run" / run / "config.json"))
    ends = [r.get("finished_at") for r in res.values() if r.get("finished_at")]
    end = max(ends) if ends else None
    hours = 0.0
    if end:
        hours = (datetime.fromisoformat(end) - datetime.fromisoformat(cfg["started"])).total_seconds() / 3600
    worker_h = sum(r.get("seconds_total") or 0 for (n, m), r in res.items()
                   if not r.get("alias_of")) / 3600
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    later = subprocess.run(["git", "log", "--reverse", "--format=%h %s", f"{cfg['commit']}..HEAD", "--",
                            "scripts/casbench/quest_bench.py", "scripts/casbench/quest_run.py"],
                           cwd=REPO, capture_output=True, text=True).stdout.strip().splitlines()
    return cfg, end, hours, worker_h, head, later


def write_ledger(run) -> str:
    body, man, res, modes = report(run)
    cfg, end, hours, worker_h, head, later = provenance(run, res)
    flagged = sorted(n for n, r in man.items() if r.get("flags"))
    declined = sorted({n for (n, m), r in res.items() if r["status"] == "declined"})
    capped = sorted(f"{n} ({m})" for (n, m), r in res.items() if r["status"] == "wall_cap")
    flagged_mols = ", ".join(sorted({n.rsplit("-x", 1)[0] for n in flagged})) or "none"
    later_lines = "\n".join(f"  - `{c}`" for c in later) or "  - none"
    rescored = sorted({n for (n, m), r in res.items()
                       if (r.get("scoring") or {}).get("rescored") and not r.get("alias_of")})
    text = f"""# casbench: QUESTDB, the CAS engine against APC-2

Written by `scripts/casbench/quest_report.py --run {run} --write` at commit
`{head}`. Do not edit by hand: the next write overwrites it. Interpretation
belongs in `docs/CAS_ENGINE_METHOD.md`, not here. The harness and its
validation are described in `docs/casbench/questdb-phase0.md`. Every
aggregate below is recomputed by a second, independent path with
`quest_report.py --check`. The M values behind the M_max split are not part
of that check: both paths read them from `quest_mdiag.py`, which validates them
against King's SI Table S12 and his quartiles before it writes them.

## What was run

- **Benchmark:** the {len(man)} QUESTDB vertical excitations of King, Hermes,
  Truhlar and Gagliardi, JCTC 2022, 18, 6065, with their geometries, state
  averages and theoretical best estimates (TBEs). Data from Zenodo record
  14889616 (CC-BY 4.0).
- **Basis:** aug-cc-pVTZ, as in King's headline result.
- **Three modes per excitation, one harness:** `apc2` reruns King's APC-2
  selector here, eps 1e-3, capped at max(12,12) = 226,512 CSFs. `engine` is
  the NexusQC engine's own space for the state, uncapped. `engine_capped` is
  that space cut to the same CSF budget by lowest entropy.
- **Downstream, identical for every mode:** SA-CASSCF, tPBE, tPBE0
  (0.75 tPBE + 0.25 SA-CASSCF) and SC-NEVPT2. NEVPT2 is skipped above 24
  active orbitals, because a (4,40) space needed 98 GB.
- **Scoring:** King's rule. The target is the highest-tPBE root of the target
  irrep and spin. The ground state is the lowest-tPBE root of its group.
- **Good space:** |SA-CASSCF − TBE| < {GOOD} eV, King's filter. King reports
  436/542 good.
- **Run:** started {cfg['started']} at commit `{cfg['commit']}`. The last row
  finished {end}, {hours:.0f} h of wall time. {cfg['workers']} workers ran at
  once, each with {cfg['threads']} OpenMP threads and 48 GB. The rows took
  {worker_h:.0f} worker-hours in total. Every row ran in its own subprocess.
- **Harness changes during the run:** each row's subprocess loads the
  harness when it starts, so later rows ran on later commits. None of these
  changes alters a computed energy. Rows that hit a memory error before the
  memory fixes were reset and rerun.
{later_lines}
- **Re-scored rows:** {len(rescored)} excitations were carried over from the
  calibration batch, which picked the target root in CASSCF order. Their
  stored per-state energies are re-scored here by King's rule rather than
  rerun: {", ".join(rescored) or "none"}.

## How to read the tables

- **Denominator:** every table counts all excitations of its category. A row
  that produced no good space counts as not good, whatever the reason, as in
  King's 436/542.
- **scored:** rows that produced energies.
- **not converged:** SA-CASSCF stopped without converging. The row has
  energies and is scored.
- **wall cap:** SA-CASSCF was still running at the 48 h per-row cap. The row
  has no energies. These are {len(capped)} rows: {", ".join(capped) or "none"}.
- **unrepresentable:** the space holds no CSF of the target irrep and spin,
  so the requested state cannot exist in it. This is the engine's answer for
  that state. It is mostly a valence space asked for a Rydberg state.
- **too large:** the native engine space has more than 1e6 CSFs. The
  `engine_capped` row then runs the capped space.
- **declined:** the engine perceived no geometric targets and built no
  space. These are: {", ".join(declined) or "none"}.
- **failed:** two attempts without a result, for any other reason.
- **missing:** no row was recorded.
- **Error statistics:** each is given three ways. Over each selector's own
  good rows is King's convention. Over the rows good for both selectors in a
  pair, a stricter filter cannot buy a lower error. Over every scored row,
  there is no filter at all.
- **`king`:** King et al.'s own Aug(12,12) numbers from Zenodo for the same
  excitations, scored by the same filter.
- **M_max split:** M_max is the larger of the ground- and excited-state M
  diagnostics (Tishchenko, Zheng and Truhlar, JCTC 2008). King's cut is
  0.14, the lowest M_max of any double excitation. Here M is computed by
  `quest_mdiag.py` from King's own Aug(12,12) wave functions, as King
  computed it, so the split is the same for all three modes. That script
  reproduces all 16 values in King's SI Table S12 and his quartiles over
  436 good rows (0.08 / 0.11 / 0.44) before it writes anything.
- **The run's own stored M is not used:** the harness counted the dominant
  configuration's open shells from the largest single determinant in the
  CASSCF orbitals. Those orbitals are any rotation of the active space, so
  the count was wrong for about a fifth of closed-shell ground states. The
  run did not keep its CI vectors, so its M cannot be redone. The harness
  is fixed for later runs and now stores each state's natural occupations.
- **Flagged geometries:** King's SI names {flagged_mols} as possibly carrying
  a unit-conversion error. Their {len(flagged)} rows are run on King's
  geometries as given, and marked in the last column below.

## Results
{body}
{per_excitation(man, res, modes)}
"""
    LEDGER.write_text(text)
    return text


def naive_errors(run, man):
    """Errors per (excitation, mode) straight from the JSONL, by a second path.

    Takes the last final line per task, follows aliases by hand and
    recomputes each error from excitation energy and TBE rather than reading
    the stored error. A calibration-era row picked its target by CASSCF
    order; King's rule is applied to it here, written out again rather than
    calling rescore().
    """
    last = {}
    for l in open(CACHE / "run" / run / "results.jsonl"):
        try:
            r = json.loads(l)
        except Exception:                                       # noqa: BLE001
            continue
        if r.get("status") not in (None, "error"):
            last[(r.get("name"), r.get("mode"))] = r
    errs = {}
    for (n, m), r in last.items():
        if r.get("status") == "alias":
            r = last.get((n, r.get("alias_of")), {})
        ex = r.get("excitation_ev") or {}
        if r.get("states") and "scoring" not in r:
            per, ti = r["states"], man[n]["target_index"]
            same = lambda i, j: (per[i]["sym"], per[i]["ss"]) == (per[j]["sym"], per[j]["ss"])  # noqa: E731
            g = sorted((i for i in range(len(per)) if same(i, 0)), key=lambda i: per[i]["e_tpbe"])[0]
            t = sorted((i for i in range(len(per)) if same(i, ti) and i != g),
                       key=lambda i: -per[i]["e_tpbe"])[0]
            ex = {k: (None if per[t].get(f"e_{k}") is None
                      else 27.211386245988 * (per[t][f"e_{k}"] - per[g][f"e_{k}"])) for k in METHODS}
        if ex.get("casscf") is None:
            continue
        errs[(n, m)] = {k: (None if ex.get(k) is None else ex[k] - man[n]["tbe_ev"]) for k in METHODS}
    for n, row in man.items():
        k = row["king"]["Aug1212"]
        if k.get("CASSCF") is not None:
            errs[(n, "king")] = {m: (None if k.get(KING_KEY[m]) is None else k[KING_KEY[m]] - row["tbe_ev"])
                                 for m in METHODS}
    return last, errs


def check(run) -> int:
    """Recompute every aggregate in the ledger by the naive path and compare.

    For every split: good-space and scored counts, own-good-rows MAE, the
    unfiltered MAE, and the size and MAEs of every pair intersection.
    """
    man = {r["name"]: r for r in json.load(open(CACHE / "manifest.json"))["rows"]}
    last, errs = naive_errors(run, man)
    _, res = load(run)
    modes = [m for m in MODES if any(mm == m for _, mm in res)]
    order = modes + ["king"]
    mae = lambda v: sum(abs(x) for x in v) / len(v) if v else None  # noqa: E731
    close = lambda a, b: (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-9)  # noqa: E731
    compared = mismatched = 0

    def cmp(what, a, b):
        nonlocal compared, mismatched
        compared += 1
        if not close(a, b) if not isinstance(a, int) else a != b:
            mismatched += 1
            print(f"  MISMATCH {what}: recomputed {a}, report {b}")

    for label, f in splits():
        names = [n for n in man if f(man[n])]
        if not names:
            continue
        N = numbers(man, res, modes, f)
        good = {m: {n for n in names if (n, m) in errs and abs(errs[(n, m)]["casscf"]) < GOOD} for m in order}
        for m in order:
            x = N["sel"][m]
            cmp(f"{label}/{m} good", len(good[m]), x["good"])
            cmp(f"{label}/{m} scored", sum(1 for n in names if (n, m) in errs), x["scored"])
            for k in METHODS:
                own = [errs[(n, m)][k] for n in good[m] if errs[(n, m)][k] is not None]
                cmp(f"{label}/{m} own MAE {k}", mae(own), x["own"][k] and x["own"][k]["mae"])
                al = [errs[(n, m)][k] for n in names if (n, m) in errs and errs[(n, m)][k] is not None]
                cmp(f"{label}/{m} unfiltered MAE {k}", mae(al), x["all"][k] and x["all"][k]["mae"])
        for (a, b), c in N["pairs"].items():
            both = good[a] & good[b]
            cmp(f"{label}/{a} vs {b} n", len(both), c["n"])
            for k in METHODS:
                bm = [n for n in both if errs[(n, a)][k] is not None and errs[(n, b)][k] is not None]
                ra = mae([errs[(n, a)][k] for n in bm])
                rb = mae([errs[(n, b)][k] for n in bm])
                cmp(f"{label}/{a} vs {b} {k} a", ra, c[k] and c[k][0])
                cmp(f"{label}/{a} vs {b} {k} b", rb, c[k] and c[k][1])
        print(f"{label}: {len(names)} excitations; good " +
              ", ".join(f"{m} {len(good[m])}" for m in order))
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
    missing = [(n, m) for n in man for m in MODES if (n, m) not in last]
    print(f"{compared} numbers compared, {mismatched} mismatched")
    print(f"tasks with more than one final line: {len(d)}" + (f" {list(d)[:10]}" if d else ""))
    print(f"tasks with no final line: {len(missing)}" + (f" {missing[:10]}" if missing else ""))
    return 1 if (mismatched or d) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true", help=f"write {LEDGER.relative_to(REPO)}")
    a = ap.parse_args()
    if a.check:
        return check(a.run)
    if a.write:
        write_ledger(a.run)
        print(f"wrote {LEDGER.relative_to(REPO)}")
        return 0
    print(report(a.run)[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
