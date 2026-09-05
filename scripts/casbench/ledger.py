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


# What the source looked like when the run started, worked out once. A
# `--set all` run writes one ledger per set as each finishes, and the writing
# itself modifies `docs/casbench/`, so asking afresh each time would report the
# run's own output as a change to the code that produced it.
_STAMP = None

# Only these decide what a benchmark returns. A modified document or tracker
# does not change a measurement, and treating it as though it did would make
# the marker meaningless in any session that edits anything at all.
#
# The `:/` prefix anchors each pathspec at the top of the working tree. Without
# it they would resolve against the cwd these commands run in, which is this
# file's own directory, and the filter would silently match nothing and report
# every tree as clean.
_SOURCE_PATHS = (":/app", ":/scripts/casbench")


def _commit() -> str:
    """The commit the run measured, marked if the source was not clean at it.

    A bare hash is a claim that the ledger below it is what that commit
    produces, and nothing used to check that claim. The stamp is read from
    `rev-parse HEAD`, which reports the last commit rather than the code in the
    working tree, so a run made with edits in place was recorded as though it
    came from the commit those edits are not in. That is not hypothetical:
    `docs/casbench/spaces.md` was committed carrying numbers from after a
    perception fix under a hash from before it, and a later session comparing
    the two had no way to see the discrepancy.

    A dirty tree is not an error and is usually the right thing to be doing,
    since measuring a change is the whole point of an iterative campaign. It
    only has to be legible afterwards, which is what `+dirty` buys.
    """
    global _STAMP
    if _STAMP is not None:
        return _STAMP
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=here, capture_output=True, text=True,
                             timeout=10)
        sha = out.stdout.strip()
        if not sha:
            _STAMP = "unknown"
            return _STAMP
        edited = subprocess.run(
            ["git", "status", "--porcelain", "--", *_SOURCE_PATHS],
            cwd=here, capture_output=True, text=True, timeout=30)
        _STAMP = sha + ("+dirty" if edited.stdout.strip() else "")
    except Exception:                                           # noqa: BLE001
        _STAMP = "unknown"
    return _STAMP


def _threads() -> str:
    """The thread counts in force, which some of these numbers depend on.

    Not decoration. A state-averaged CASSCF in this engine can have more than
    one converged solution, and which one a run reaches is decided by the
    reduction order in the linear algebra, so the same protocol on the same
    commit gives a different answer at a different thread count. A ledger that
    records only the commit cannot explain a row that moved, and two of this
    campaign's open questions are about exactly that.

    The variables are read rather than set. They belong to the environment a
    process is created with, and this module is imported far too late to change
    them.
    """
    seen = []
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        value = os.environ.get(var)
        if value:
            seen.append(f"{var.split('_')[0].lower()}={value}")
    return ", ".join(seen) if seen else "no thread limit set"


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
        f"Produced at commit `{_commit()}` on {when}, in {seconds:.0f}s, "
        f"with {_threads()}.",
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
