#!/usr/bin/env python3
"""P2.6 -- what the jobs API tells the frontend about a job.

Three things, all of which used to be decided from the runner key:

- **`task`/`subtype` are served**, so the drawer can say what a job is
  rather than naming the function that ran it.
- **`is_scan_master` / `is_ensemble_master` key on the task.** These drive
  whether the UI offers a children view at all, and a stale runner-key
  comparison against a v2 spec does not raise -- it silently returns False
  and the sub-jobs become unreachable.
- **`filename_stem` is served rather than recomputed in TypeScript.** It
  existed twice, once per language, each copy carrying a comment asking
  whoever edited it to remember the other. This asserts the two agree,
  which is the thing those comments were asking for and which no browser
  test could ever have caught: the two names appear on different
  downloads, so a drift shows up as two files in a folder that should have
  matched, months later.

Run:  PYTHONPATH=$PWD python3 tests/backend/tax_02_job_rows.py
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid

from app.chemistry.jobs.naming import job_filename_stem
from app.chemistry.molecule import resolve_molecule
from app.config import JOBS_DIR

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


WATER = resolve_molecule("water").to_dict()
MADE: list[str] = []


def make_job(**spec_fields) -> str:
    job_id = f"tax02-{uuid.uuid4().hex[:8]}"
    d = JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    spec = {
        "job_id": job_id, "method": "single_point", "task": "", "subtype": "",
        "engine": "pyscf", "molecule": WATER, "params": {"method": "hf", "basis": "sto-3g"},
        "label": None, "created_at": 1787000000.0, "parent_job_id": None,
    }
    spec.update(spec_fields)
    (d / "spec.json").write_text(json.dumps(spec))
    (d / "meta.json").write_text(json.dumps({"status": "completed"}))
    (d / "status.json").write_text(json.dumps(
        {"status": "completed", "message": "done", "updated_at": 1787000001.0}))
    MADE.append(job_id)
    return job_id


def slugify_like_the_browser(label: str, max_len: int = 80) -> str:
    """`slugifyLabel` from frontend/src/lib/jobFilename.ts, transliterated.

    Kept here rather than run through node: the point is to compare the two
    *algorithms*, and a Python transliteration that has to be updated
    alongside the TypeScript is exactly the maintenance burden the dedupe
    removes -- so this exists only to prove the served stem makes it
    unnecessary, and the assertion below is that the browser no longer
    needs it at all.
    """
    replaced = "".join(c if (c.isalnum() and c.isascii()) or c in "._-" else "_"
                       for c in (label or ""))
    while "__" in replaced:
        replaced = replaced.replace("__", "_")
    collapsed = replaced.strip("._-")
    return collapsed[:max_len].rstrip("._-")


def main() -> int:
    from server.routes.jobs import _job_row

    try:
        print("== the row carries the v2 taxonomy ==")
        job_id = make_job(method="geometry_optimization", task="opt", subtype="min")
        row = _job_row(job_id)
        check("task is served", row["task"] == "opt", f"got {row['task']!r}")
        check("subtype is served", row["subtype"] == "min", f"got {row['subtype']!r}")
        check("and the runner key is still there for the result renderers",
              row["method"] == "geometry_optimization", f"got {row['method']!r}")

        print("\n== master flags key on the task ==")
        scan = make_job(method="pes_scan", task="pes_1d")
        check("a 1-D scan is a scan master", _job_row(scan)["is_scan_master"])
        check("and not an ensemble master", not _job_row(scan)["is_ensemble_master"])

        path = make_job(method="pes_scan", task="interp_pes")
        check("an interpolated path is also a scan master",
              _job_row(path)["is_scan_master"])

        ens = make_job(method="wigner_ensemble", task="wigner_spectra")
        check("a nuclear-ensemble job is an ensemble master",
              _job_row(ens)["is_ensemble_master"])
        check("and not a scan master", not _job_row(ens)["is_scan_master"])

        plain = make_job(method="single_point", task="single_point", subtype="gs")
        check("a single point is neither",
              not _job_row(plain)["is_scan_master"]
              and not _job_row(plain)["is_ensemble_master"])

        # The fallback matters: a job submitted between the agent rebuild
        # and the taxonomy switch has a runner key and no task, and its
        # children must stay reachable.
        legacy = make_job(method="pes_scan", task="")
        check("a task-less pre-switch scan is still a master",
              _job_row(legacy)["is_scan_master"])

        print("\n== the filename stem is served, and the two agree ==")
        row = _job_row(job_id)
        check("filename_stem is on the row", bool(row.get("filename_stem")),
              f"got {row.get('filename_stem')!r}")
        expected = job_filename_stem(
            job_id, json.loads((JOBS_DIR / job_id / "spec.json").read_text()),
            json.loads((JOBS_DIR / job_id / "meta.json").read_text()), 1787000000.0)
        check("and is exactly what naming.py produces", row["filename_stem"] == expected,
              f"row={row['filename_stem']!r} naming={expected!r}")
        check("it ends in the short job id, so two runs of one calculation differ",
              row["filename_stem"].endswith(job_id[:8]), row["filename_stem"])
        check("and starts with a UTC date", row["filename_stem"][:8].isdigit(),
              row["filename_stem"])

        # The label round-trips through the same slug rules the browser used
        # to apply for itself.
        awkward = make_job(task="single_point", subtype="gs")
        (JOBS_DIR / awkward / "meta.json").write_text(json.dumps(
            {"status": "completed", "label": 'water "test"\nrun/2'}))
        stem = _job_row(awkward)["filename_stem"]
        check("a label with quotes, a newline and a slash is made filename-safe",
              all(c not in stem for c in '"\n/'), stem)
        check("and matches the browser's own slug rules",
              slugify_like_the_browser('water "test"\nrun/2') in stem,
              f"stem={stem!r}")
    finally:
        for job_id in MADE:
            shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
