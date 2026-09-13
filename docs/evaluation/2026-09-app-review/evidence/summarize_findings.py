#!/usr/bin/env python3
"""Generate the findings summary tables for report.md straight from
findings.md, so every count in the report is reproducible and carries its
ids. Run from anywhere in the repo:

    python3 docs/evaluation/2026-09-app-review/evidence/summarize_findings.py

Prints a severity x class matrix (counts), a per-severity id list, and a
per-class id list. The cleared entry (R-102) and the R-000 template are
excluded. This is the source for report.md's "Findings by severity and class".
"""
from __future__ import annotations
import collections
import re
from pathlib import Path

REG = Path(__file__).resolve().parent.parent / "findings.md"
SEV_ORDER = ["S1", "S2", "S3", "S4"]
CLS_ORDER = ["security", "bug", "perf", "docs", "comfort"]


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
        sev = (re.search(r"^- severity: (\S+)", seg, flags=re.M) or [None, "?"])[1][:2]
        cls = (re.search(r"^- class: (\w+)", seg, flags=re.M) or [None, "?"])[1]
        conf = (re.search(r"^- confidence: (.+)$", seg, flags=re.M) or [None, "?"])[1]
        if rid == "R-102" or "cleared" in sev.lower():
            continue
        confirmed = conf.strip().lower().startswith(("confirmed", "reproduced")) or "confirmed" in conf.lower()
        out.append({"id": rid, "title": title, "sev": sev, "cls": cls, "confirmed": confirmed})
    return out


def main():
    rows = parse()
    print(f"# {len(rows)} findings (excluding the cleared R-102 and the template)\n")

    # matrix
    mat = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        mat[r["sev"]][r["cls"]] += 1
    print("## Severity x class")
    print("| | " + " | ".join(CLS_ORDER) + " | total |")
    print("|---|" + "---|" * (len(CLS_ORDER) + 1))
    for sev in SEV_ORDER:
        cells = [str(mat[sev][c] or "") for c in CLS_ORDER]
        tot = sum(mat[sev].values())
        print(f"| {sev} | " + " | ".join(cells) + f" | {tot} |")
    totals = [str(sum(mat[s][c] for s in SEV_ORDER)) for c in CLS_ORDER]
    print("| total | " + " | ".join(totals) + f" | {len(rows)} |")

    n_conf = sum(1 for r in rows if r["confirmed"])
    print(f"\nConfirmed (code-read, executed, or live): {n_conf} of {len(rows)}. "
          f"The rest are suspected-from-code-read, for the fix phase to reproduce.\n")

    print("## Ids by severity")
    for sev in SEV_ORDER:
        ids = [r["id"] for r in rows if r["sev"] == sev]
        print(f"- **{sev}** ({len(ids)}): " + ", ".join(ids))

    print("\n## The S1 findings, named")
    for r in rows:
        if r["sev"] == "S1":
            mark = "confirmed" if r["confirmed"] else "suspected"
            print(f"- {r['id']} [{r['cls']}, {mark}]: {r['title']}")


if __name__ == "__main__":
    main()
