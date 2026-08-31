#!/usr/bin/env python3
"""The project registry keeps a job in at most one project, and keeps that
true through a single atomic write.

    PYTHONPATH=$PWD python3 tests/backend/proj_01_registry.py

Archiving a job is a membership label, never a move, so the whole feature
rests on one flat JSON file staying internally consistent. The specific
faults pinned here:

  * Filing a job into a second project must MOVE it, not copy it. A job
    listed under two projects would be downloaded twice, counted twice in
    two archive sizes, and would return to the job manager from one project
    while still being hidden by the other.
  * That move must be one read-modify-write cycle. The obvious spelling,
    remove_jobs(other, ids) followed by add_jobs(this, ids), is two file
    writes with a window between them where the job belongs to nothing;
    this asserts on the file's bytes, which is the only way to see the
    difference, since both spellings produce the same end state.
  * A job whose directory is gone must never be reported as a member.
    Quota eviction and DELETE /api/jobs/{id} both remove directories, and a
    project naming a dead id reports an archive no download can produce.
  * prune_job is what delete_job_dir calls, so it has to drop the id from
    whichever project holds it without disturbing the others.

Pure functions against a temporary registry file. No stack, no jobs
created, and so none to clean up.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.projects import registry  # noqa: E402

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if not ok and detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="qatest_projects_"))
    jobs_dir = tmp / "jobs"
    jobs_dir.mkdir()

    # Point the module at a scratch registry and a scratch job tree, so this
    # never reads or writes the real data/ directory.
    registry.PROJECTS_FILE = tmp / "projects.json"
    registry.JOBS_DIR = jobs_dir

    def make_job(job_id: str) -> str:
        d = jobs_dir / job_id
        d.mkdir()
        (d / "spec.json").write_text("{}")
        return job_id

    a, b, c = (make_job(x) for x in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"))

    print("\n== creating and reading back ==")
    p1 = registry.create_project("Uracil photochemistry")
    p2 = registry.create_project("Benzene benchmarks", description="basis set sweep")
    check("a new project starts empty", p1["job_ids"] == [], str(p1))
    check("the description round-trips", registry.get_project(p2["project_id"])["description"] == "basis set sweep")
    check("both projects are listed", len(registry.list_projects()) == 2)
    check("an unknown id reads back as None", registry.get_project("nope") is None)

    print("\n== a job belongs to exactly one project ==")
    registry.add_jobs(p1["project_id"], [a, b])
    check("both jobs filed", set(registry.get_project(p1["project_id"])["job_ids"]) == {a, b})

    registry.add_jobs(p2["project_id"], [a])
    one = registry.get_project(p1["project_id"])["job_ids"]
    two = registry.get_project(p2["project_id"])["job_ids"]
    check("filing into a second project MOVES rather than copies",
          one == [b] and two == [a], f"project one {one}, project two {two}")

    registry.add_jobs(p1["project_id"], [b])
    check("re-adding a job the project already holds does not duplicate it",
          registry.get_project(p1["project_id"])["job_ids"] == [b])

    registry.add_jobs(p1["project_id"], [c, c])
    check("a repeated id in one call is stored once",
          registry.get_project(p1["project_id"])["job_ids"].count(c) == 1)

    print("\n== the move is one atomic write ==")
    # Both projects live in the same file, so a correct implementation
    # rewrites it once. A remove-then-add spelling writes twice and leaves a
    # window where the job belongs to neither -- invisible in the end state,
    # visible here.
    writes = {"n": 0}
    real_write = registry._atomic_write_text

    def counting_write(text: str) -> None:
        writes["n"] += 1
        # Every intermediate state on disk must still hold the job somewhere.
        holders = [p["name"] for p in json.loads(text) if a in p["job_ids"]]
        check(f"write #{writes['n']} leaves the job owned by exactly one project",
              len(holders) == 1, f"held by {holders}")
        real_write(text)

    registry._atomic_write_text = counting_write
    registry.add_jobs(p1["project_id"], [a])
    registry._atomic_write_text = real_write
    check("moving a job between projects is a single file write",
          writes["n"] == 1, f"{writes['n']} writes, so the move is not atomic")

    print("\n== a job whose directory is gone stops being a member ==")
    import shutil
    shutil.rmtree(jobs_dir / c)
    check("a dead id is filtered out of a project's members",
          c not in registry.get_project(p1["project_id"])["job_ids"])
    check("and out of the job -> project map", c not in registry.job_project_map())
    check("the surviving members are untouched",
          set(registry.get_project(p1["project_id"])["job_ids"]) == {a, b})

    print("\n== removing, mapping and pruning ==")
    registry.remove_jobs(p1["project_id"], [a])
    check("a removed job leaves the project", registry.get_project(p1["project_id"])["job_ids"] == [b])
    check("but its directory is untouched, because archiving is never a move",
          (jobs_dir / a / "spec.json").exists())

    registry.add_jobs(p2["project_id"], [a])
    mapping = registry.job_project_map()
    check("the map names each job's project",
          mapping[a]["project_name"] == "Benzene benchmarks" and mapping[b]["project_name"] == "Uracil photochemistry",
          str(mapping))

    registry.prune_job(a)
    check("prune_job drops the id from the project holding it",
          registry.get_project(p2["project_id"])["job_ids"] == [])
    check("and leaves every other project alone",
          registry.get_project(p1["project_id"])["job_ids"] == [b])

    print("\n== renaming and deleting ==")
    registry.update_project(p1["project_id"], name="Uracil, revisited")
    check("a rename sticks", registry.get_project(p1["project_id"])["name"] == "Uracil, revisited")
    check("and reaches the job -> project map",
          registry.job_project_map()[b]["project_name"] == "Uracil, revisited")
    registry.update_project(p1["project_id"], description="only the description")
    check("updating one field leaves the other alone",
          registry.get_project(p1["project_id"])["name"] == "Uracil, revisited")
    check("a blank rename is ignored rather than blanking the name",
          registry.update_project(p1["project_id"], name="   ")["name"] == "Uracil, revisited")

    gone = registry.delete_project(p1["project_id"])
    check("delete_project returns the entry, so a caller can still cascade",
          gone is not None and gone["job_ids"] == [b], str(gone))
    check("the project is gone from the list", registry.get_project(p1["project_id"]) is None)
    check("its jobs are NOT touched on disk", (jobs_dir / b / "spec.json").exists())

    p3 = registry.create_project("third")
    removed = registry.delete_projects([p2["project_id"], p3["project_id"], "nonexistent"])
    check("delete_projects removes every id it recognises", len(removed) == 2, str(removed))
    check("and leaves the registry empty", registry.list_projects() == [])

    print("\n== a corrupt or missing file fails open ==")
    registry.PROJECTS_FILE.write_text("{ not json")
    check("a corrupt registry reads back as empty rather than raising", registry.list_projects() == [])
    registry.PROJECTS_FILE.unlink()
    check("a missing registry reads back as empty", registry.list_projects() == [])

    shutil.rmtree(tmp)
    print(f"\n{checks - len(failures)}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
