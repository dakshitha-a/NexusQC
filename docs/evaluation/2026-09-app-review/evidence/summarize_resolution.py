#!/usr/bin/env python3
"""Generate the fix phase's close-out tables straight from findings.md, so
every count in resolution.md is reproducible and carries its ids. Companion
to summarize_findings.py, which does the same job for the review's own
report. Run from anywhere in the repo:

    python3 docs/evaluation/2026-09-app-review/evidence/summarize_resolution.py

It reads the two lines the fix phase appends to each register entry:

    - resolution: fixed <hash> | not reproduced | won't fix, <reason>
    - regression test: <path>

and prints: coverage (how many of the open findings carry a resolution, and
which do not), an outcome x severity matrix with ids, the fixed entries that
name no regression test, and every named test path that does not exist on
disk. A finding with no resolution line is the thing this script exists to
find, so it is listed by id rather than only counted.

The cleared R-102 and the R-000 template are excluded throughout, the same
exclusion summarize_findings.py makes, so the denominator here (102) is the
denominator the report quotes.
"""
from __future__ import annotations
import collections
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
REG = Path(__file__).resolve().parent.parent / "findings.md"
SEV_ORDER = ["S1", "S2", "S3", "S4"]
OUTCOMES = ["fixed", "not reproduced", "won't fix"]


def parse():
    t = REG.read_text()
    out = []
    heads = list(re.finditer(r"^### (R-\d{3}): (.+)$", t, flags=re.M))
    for i, m in enumerate(heads):
        rid, title = m.group(1), m.group(2)
        if rid == "R-000":
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(t)
        seg = t[m.end():end]

        def field(name):
            mm = re.search(rf"^- {name}: (.+)$", seg, flags=re.M)
            return mm.group(1).strip() if mm else None

        sev = (field("severity") or "?")[:2]
        if rid == "R-102" or "cleared" in sev.lower():
            continue
        res = field("resolution")
        outcome = None
        if res:
            low = res.lower()
            for o in OUTCOMES:
                if low.startswith(o):
                    outcome = o
                    break
            outcome = outcome or "other"
        out.append({
            "id": rid, "title": title, "sev": sev,
            "cls": field("class") or "?",
            "resolution": res, "outcome": outcome,
            "test": field("regression test"),
        })
    return out


def main() -> int:
    rows = parse()
    n = len(rows)
    print(f"# Resolution of the {n} open findings\n")

    missing = [r["id"] for r in rows if not r["resolution"]]
    print(f"Carrying a resolution: {n - len(missing)} of {n}.")
    if missing:
        print(f"**Missing ({len(missing)}):** " + ", ".join(missing))
    print()

    mat = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        mat[r["sev"]][r["outcome"] or "(none)"] += 1
    cols = OUTCOMES + ["other", "(none)"]
    print("## Outcome by severity\n")
    print("| | " + " | ".join(cols) + " | total |")
    print("|---|" + "---|" * (len(cols) + 1))
    for sev in SEV_ORDER:
        cells = [str(mat[sev][c] or "") for c in cols]
        print(f"| {sev} | " + " | ".join(cells) + f" | {sum(mat[sev].values())} |")
    totals = [str(sum(mat[s][c] for s in SEV_ORDER)) for c in cols]
    print("| total | " + " | ".join(totals) + f" | {n} |")

    print("\n## Ids by outcome\n")
    for o in cols:
        ids = [r["id"] for r in rows if (r["outcome"] or "(none)") == o]
        if ids:
            print(f"- **{o}** ({len(ids)}): " + ", ".join(ids))

    untested = [r["id"] for r in rows if r["outcome"] == "fixed" and not r["test"]]
    print(f"\n## Fixed entries naming no regression test: {len(untested)}")
    if untested:
        print("  " + ", ".join(untested))

    import subprocess
    unreachable = []
    for r in rows:
        if not r["resolution"]:
            continue
        for tok in re.findall(r"\b[0-9a-f]{7,40}\b", r["resolution"]):
            ok = subprocess.run(["git", "merge-base", "--is-ancestor", tok, "HEAD"],
                                cwd=REPO, capture_output=True).returncode == 0
            if not ok:
                unreachable.append(f"{r['id']}: {tok}")
    print(f"\n## Resolution hashes not reachable from HEAD: {len(unreachable)}")
    for u in unreachable:
        print("  " + u)

    bad = []
    for r in rows:
        if not r["test"]:
            continue
        for tok in re.findall(r"[\w./-]+", r["test"]):
            if "/" in tok and not tok.endswith((".md", ".",)) and not (REPO / tok).exists():
                bad.append(f"{r['id']}: {tok}")
    print(f"\n## Named test paths that do not exist on disk: {len(bad)}")
    for b in bad:
        print("  " + b)

    return 1 if (missing or untested or bad or unreachable) else 0


if __name__ == "__main__":
    sys.exit(main())
