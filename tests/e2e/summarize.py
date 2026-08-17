"""Builds the report's tables from tests/e2e/results/*.jsonl.

The report is assembled from this file rather than from terminal
scrollback, so a crash partway through a multi-hour run costs one
scenario rather than the whole record -- and so the numbers in the report
are never transcribed by hand.

    python3 tests/e2e/summarize.py            # human-readable
    python3 tests/e2e/summarize.py --markdown # tables for the report
"""
from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def load() -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(RESULTS / "*.jsonl"))):
        for line in open(f):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    # Last write per scenario wins -- a re-run supersedes an earlier attempt.
    latest: dict[str, dict] = {}
    for r in rows:
        sid = r.get("scenario")
        if sid:
            latest[sid] = r
    return [latest[k] for k in sorted(latest)]


def markdown(rows: list[dict]) -> None:
    matrix = [r for r in rows if r.get("scenario", "").startswith("M")]
    other = [r for r in rows if not r.get("scenario", "").startswith("M")]

    print("### Job matrix\n")
    print("| cell | job_type | engine | tier | verdict | wall | summary keys |")
    print("|---|---|---|---|---|---|---|")
    for r in matrix:
        keys = ", ".join((r.get("summary_keys") or [])[:3])
        el = r.get("elapsed")
        print(f"| {r['scenario']} | `{r.get('job_type','')}` | {r.get('engine','')} "
              f"| {r.get('tier','')} | **{r.get('verdict','')}** "
              f"| {str(el) + 's' if el else '—'} | {keys or '—'} |")

    print("\n### Other scenarios\n")
    print("| id | verdict | detail |")
    print("|---|---|---|")
    for r in other:
        d = str(r.get("detail", ""))[:110].replace("|", "\\|").replace("\n", " ")
        print(f"| {r['scenario']} | **{r.get('verdict','')}** | {d} |")

    print("\n### Verdict counts\n")
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.get("verdict", "?")] += 1
    print("| verdict | n |")
    print("|---|---|")
    for k in sorted(counts):
        print(f"| {k} | {counts[k]} |")

    # Timing
    timed = [r for r in rows if isinstance(r.get("elapsed"), (int, float))]
    if timed:
        timed.sort(key=lambda r: r["elapsed"], reverse=True)
        print("\n### Slowest scenarios\n")
        print("| id | wall (s) | turn (s) |")
        print("|---|---|---|")
        for r in timed[:10]:
            print(f"| {r['scenario']} | {r['elapsed']} | {r.get('turn_elapsed','—')} |")


def human(rows: list[dict]) -> None:
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.get("verdict", "?")] += 1
        print(f"{r.get('scenario','?'):22s} {r.get('verdict','?'):9s} "
              f"{r.get('job_type','') or r.get('detail','') or ''}"[:110])
    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    rows = load()
    if "--markdown" in sys.argv:
        markdown(rows)
    else:
        human(rows)
