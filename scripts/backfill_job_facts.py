#!/usr/bin/env python3
"""Rewrite results and plots already on disk into the canonical vocabulary.

Run once, after deploying the change that introduced
`app/chemistry/jobs/facts.py`. New jobs are canonical from the moment they are
written; this is only for what was already stored.

Two stores, and forgetting the second is the easy mistake. Job results live in
`data/jobs/<id>/result.json`. Plots live in `data/plots/[<owner>/]<id>/record.json`
and hold two things that name summary fields: a custom plot's
`spec.series[].y_field` field paths, and the `data` block of cached numbers
that `plot_context_summary` answers questions from. A plot whose spec still
says `casscf_energy_hartree` will not re-render and cannot be edited once no
job writes that name any more, and it fails by drawing an empty chart rather
than by raising.

Idempotent: running it twice is a no-op, because `canonicalize` is.

    python3 scripts/backfill_job_facts.py            # report only
    python3 scripts/backfill_job_facts.py --write    # actually rewrite
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.chemistry.jobs.facts import canonicalize  # noqa: E402
from app.config import JOBS_DIR, PLOTS_DIR  # noqa: E402

# Every rename the vocabulary made, as a flat old -> new map, for rewriting
# the field paths and cached-data keys held inside plot records. The energy
# aliases all collapse onto one name.
FIELD_RENAMES = {
    "final_energy_hartree": "total_energy_hartree",
    "ground_state_energy_hartree": "total_energy_hartree",
    "ground_state_ccsd_energy_hartree": "total_energy_hartree",
    "casscf_energy_hartree": "total_energy_hartree",
    "caspt2_energy_hartree": "total_energy_hartree",
    "electronic_energy_hartree": "total_energy_hartree",
    "energy_hartree": "total_energy_hartree",
    "optimized_molecule": "optimized_geometry",
}


def rename_in_path(path: str) -> str:
    """Rewrite the leading key of a field path, leaving subscripts alone."""
    if not isinstance(path, str):
        return path
    head, sep, rest = path.partition("[")
    key, dot, tail = head.partition(".")
    if key in FIELD_RENAMES:
        head = FIELD_RENAMES[key] + dot + tail
    return head + sep + rest


def backfill_jobs(write: bool) -> tuple[int, int]:
    seen = changed = 0
    for result_path in sorted(Path(JOBS_DIR).glob("*/result.json")):
        seen += 1
        try:
            doc = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print("  skip %s: %s" % (result_path.parent.name, e))
            continue
        spec_path = result_path.parent / "spec.json"
        spec = {}
        if spec_path.exists():
            try:
                spec = json.loads(spec_path.read_text())
            except json.JSONDecodeError:
                pass
        before = doc.get("summary")
        after = canonicalize(before, spec)
        if after == before:
            continue
        changed += 1
        print("  %s: %s" % (result_path.parent.name,
                            ", ".join(sorted(set(after or {}) - set(before or {}))) or "reshaped"))
        if write:
            doc["summary"] = after
            result_path.write_text(json.dumps(doc, indent=2))
    return seen, changed


def backfill_plots(write: bool) -> tuple[int, int]:
    seen = changed = 0
    for record_path in sorted(Path(PLOTS_DIR).glob("**/record.json")):
        seen += 1
        try:
            rec = json.loads(record_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print("  skip %s: %s" % (record_path.parent.name, e))
            continue
        original = json.dumps(rec, sort_keys=True)

        spec = rec.get("spec") or {}
        for series in spec.get("series") or []:
            if isinstance(series, dict) and "y_field" in series:
                series["y_field"] = rename_in_path(series["y_field"])
        if isinstance(spec.get("x_field"), str):
            spec["x_field"] = rename_in_path(spec["x_field"])

        data = rec.get("data")
        if isinstance(data, dict):
            rec["data"] = {FIELD_RENAMES.get(k, k): v for k, v in data.items()}

        if json.dumps(rec, sort_keys=True) == original:
            continue
        changed += 1
        print("  %s (%s)" % (record_path.parent.name, rec.get("kind")))
        if write:
            record_path.write_text(json.dumps(rec))
    return seen, changed


def main() -> int:
    write = "--write" in sys.argv
    print("Jobs in %s:" % JOBS_DIR)
    js, jc = backfill_jobs(write)
    print("Plots in %s:" % PLOTS_DIR)
    ps, pc = backfill_plots(write)
    print("\n%d/%d job results and %d/%d plot records need rewriting."
          % (jc, js, pc, ps))
    if not write and (jc or pc):
        print("Nothing was written. Re-run with --write to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
