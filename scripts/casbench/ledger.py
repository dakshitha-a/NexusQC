"""A committed record of what the benchmark returned, so runs can be diffed.

Until now `run_bench.py` printed everything to stdout and wrote a file only
when `--out` was passed, and no benchmark output was committed anywhere. Every
quantitative claim about this engine therefore lived as prose in
`docs/CAS_ENGINE_METHOD.md`, restated by hand whenever something changed. That
is workable for a one-off write-up and useless for an iterative campaign: there
is no way to ask what moved between this run and the last one, which is the
question every change raises.

The ledger is markdown rather than a JSON dump on purpose.
`scripts/check_public_safe.sh` scans tracked files for machine-generated data,
and these are tracked files that have to stay publishable. Markdown tables also
diff readably in a pull request, which a re-serialised JSON blob does not.

Each file records the commit it was produced at and the wall time it took, so a
row can always be traced back to the code that produced it. Nothing here
interprets the numbers; that belongs in the method document.
"""
from __future__ import annotations

import datetime
import os
import subprocess


def _commit() -> str:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=here, capture_output=True, text=True,
                             timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:                                           # noqa: BLE001
        return "unknown"


def _cell(value) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value) or "-"
    if value is None:
        return "-"
    # A pipe would split the markdown cell it sits in.
    return str(value).replace("|", "/")


def _columns(rows) -> list:
    """Every key any row carries, in first-seen order.

    Union rather than intersection, because a row that errored or was skipped
    carries different keys from one that succeeded and dropping those columns
    would hide exactly the rows worth looking at.
    """
    seen = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def write(set_name: str, rows, seconds: float, out_dir: str = None) -> str:
    """Write one set's results and return the path."""
    if out_dir is None:
        here = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(here, "..", "..", "docs", "casbench")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{set_name}.md")

    rows = [r for r in (rows or []) if isinstance(r, dict)]
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# casbench: {set_name}",
        "",
        f"Produced at commit `{_commit()}` on {when}, in {seconds:.0f}s.",
        "",
        "Written by `scripts/casbench/run_bench.py`. Do not edit by hand: the",
        "next run overwrites it. Interpretation belongs in",
        "`docs/CAS_ENGINE_METHOD.md`, not here.",
        "",
    ]
    if not rows:
        lines += ["This set returned no rows.", ""]
    else:
        cols = _columns(rows)
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join("---" for _ in cols) + "|")
        for row in rows:
            lines.append("| " + " | ".join(_cell(row.get(c)) for c in cols)
                         + " |")
        lines.append("")

    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path
