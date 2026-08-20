#!/usr/bin/env python3
"""P7.4 -- `batch`: a master task fanning ONE job type out over every
geometry produced by another job, real end to end.

Three axes the user narrowed/widened on 2026-08-20, after this step first
shipped fixed at single_point/gs children over a geometry_set only:

- **Which child task runs** -- restricted to job types 1-4 (single_point,
  opt, freq, opt_freq -- registry2/tasks.py's BATCH_CHILD_TASKS), not the
  originally-planned 1-6 (pes_1d/interp_pes stay out: nesting a master
  inside a master is out of scope).
- **Which job a batch can pull geometries from** -- widened from
  geometry_set only to any of geometry_set, pes_1d, interp_pes,
  wigner_spectra, neb_ts (tasks.BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY), since
  all five already write their geometries as plain multi-frame xmol text,
  just under different artifact keys.
- **Individually-tagged (not-a-job) geometries** -- 3+ molecule-panel
  frames now serve as a batch source too, resolved by
  registry2/elicitation.py's own special-case step into
  params['_frame_geometries'] (never a declared ParamSpec, same
  "resolved from state, not typed into a field" status _end_molecule
  already has), the same "tagged geometries" input shape the plan
  originally named alongside geometry_set.

Covers, real end to end where the underlying compute is cheap: a real
geometry_set job; a real pes_1d scan and a real interp_pes path (both
read as batch geometry sources WITHOUT waiting for their own children --
proving _resolve_batch_geometries reads the path_xyz they render upfront,
not something only available once they finish); a genuine capability
refusal when the chosen (engine, method) cannot deliver what the chosen
child_task needs (opt on eom_ccsd, which has no gradient anywhere in this
app's capability matrix); real PySCF single_point/gs children (the
original, still-default-shaped case) AND real PySCF freq children (a
DIFFERENT job family, proving the widening actually dispatches something
other than single points); dispatched through
JobManager.submit_batch/batch_orchestrator.py; and the P7.3
children-pagination route reused unmodified for a third master kind.

wigner_spectra and neb_ts sources are covered with a hand-built fixture
job directory (real spec.json/status.json/result.json, a real small
multi-frame xyz file under the exact artifact key each task actually
uses) rather than a full sampling run or a full NEB search -- what is
under test here is _resolve_batch_geometries's artifact-key resolution
and multi-frame parsing, not wigner_spectra's or neb_ts's own chemistry,
which their own test scripts already cover.

Run:  PYTHONPATH=$PWD python3 tests/backend/p7_04_batch_master.py
"""
from __future__ import annotations

import sys
import time

from app.agent.tools import _build_batch_spec_or_error, _resolve_batch_geometries
from app.chemistry.jobs.base import (
    JobResult, JobSpec, get_job_manager, read_spec, read_status, sub_job_ids_of, write_result, write_status,
)
from app.chemistry.jobs.batch_orchestrator import get_batch_orchestrator
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import validate_draft

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


def _wait_terminal(sub_ids: list[str], timeout_s: float = 180) -> dict[str, str]:
    deadline = time.time() + timeout_s
    statuses: dict[str, str] = {}
    while time.time() < deadline:
        statuses = {sid: (read_status(sid) or {}).get("status") for sid in sub_ids}
        if all(s in ("completed", "failed") for s in statuses.values()):
            break
        time.sleep(1)
    return statuses


def _drain_to_completion(master_id: str, timeout_s: float = 30) -> dict:
    # Standalone script, no live server -- nothing ticks BatchOrchestrator's
    # own background thread the way server/main.py's lifespan does, so
    # drive _update_one directly, same role a live poll tick plays.
    orchestrator = get_batch_orchestrator()
    deadline = time.time() + timeout_s
    status = None
    while time.time() < deadline:
        orchestrator._update_one(master_id)
        status = read_status(master_id)
        if status and status["status"] == "completed":
            break
        time.sleep(1)
    return status


def make_geometry_set(n_frames: int = 3, label: str = "p7_04 test set") -> tuple[str, list]:
    mgr = get_job_manager()
    frames = []
    for i, dx in enumerate(x * 0.2 for x in range(n_frames)):
        frames.append({
            "name": f"water {i}",
            "symbols": list(WATER["symbols"]),
            "coords": [[c[0] + dx, c[1], c[2]] for c in WATER["coords"]],
        })
    gs_id = mgr.submit_geometry_set(frames, label=label)
    check("geometry_set job is completed immediately", read_status(gs_id)["status"] == "completed")
    geometries, error = _resolve_batch_geometries(gs_id)
    check("geometries resolve with no error", error is None, error)
    return gs_id, geometries


def _write_fixture_source_job(task: str, artifact_key: str, n_frames: int = 2) -> str:
    """A hand-built completed job directory carrying a real small
    multi-frame xyz file under `artifact_key`, standing in for a full
    wigner_spectra sampling run or a full neb_ts search -- see this
    module's own docstring for why that substitution is legitimate here."""
    import json
    import uuid

    job_id = uuid.uuid4().hex[:12]
    spec = JobSpec(method="hf", engine="orca", molecule=WATER, task=task, subtype="", job_id=job_id)
    job_dir = spec.job_dir()
    (job_dir / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))
    lines = []
    for i in range(n_frames):
        lines.append(str(len(WATER["symbols"])))
        lines.append(f"fixture frame {i}")
        for sym, (x, y, z) in zip(WATER["symbols"], WATER["coords"]):
            lines.append(f"{sym:2s} {x + 0.1 * i: .8f} {y: .8f} {z: .8f}")
    xyz_path = job_dir / f"{artifact_key}.xyz"
    xyz_path.write_text("\n".join(lines) + "\n")
    write_status(job_id, "completed", "fixture")
    write_result(JobResult(job_id, "completed", summary={}, artifacts={artifact_key: str(xyz_path)}))
    return job_id


def check_geometry_sources() -> None:
    print("\n== _resolve_batch_geometries: every accepted source task ==")

    # pes_1d and interp_pes: real masters, read WITHOUT waiting for their
    # own children -- both render path_xyz in full at submit time (see
    # JobManager.submit_scan's own docstring), so a batch can source from
    # one still in flight.
    from app.agent.tools import _build_scan_images

    mgr = get_job_manager()
    pes_master = JobSpec(
        task="pes_1d", subtype="", method="hf", engine="orca", molecule=WATER,
        params={"basis": "sto-3g", "n_points": 2, "coordinate": {"type": "bond", "atoms": [1, 2]},
                "scan_range": [0.9, 1.0], "_scan_start_molecule": WATER},
    )
    images, coord_values, coord_label, _w = _build_scan_images(pes_master.params)
    pes_id = mgr.submit_scan(pes_master, images, coord_values, coord_label)
    geoms, err = _resolve_batch_geometries(pes_id)
    check("pes_1d source resolves before its own children finish",
          err is None and geoms is not None and len(geoms) == 2, err)

    interp_master = JobSpec(
        task="interp_pes", subtype="", method="hf", engine="orca", molecule=WATER,
        params={"basis": "sto-3g", "n_points": 2, "interpolation_method": "linear",
                "_scan_start_molecule": WATER,
                "_end_molecule": {**WATER, "coords": [[c[0] + 0.3, c[1], c[2]] for c in WATER["coords"]]}},
    )
    images2, coord_values2, coord_label2, _w2 = _build_scan_images(interp_master.params)
    interp_id = mgr.submit_scan(interp_master, images2, coord_values2, coord_label2)
    geoms2, err2 = _resolve_batch_geometries(interp_id)
    check("interp_pes source resolves before its own children finish",
          err2 is None and geoms2 is not None and len(geoms2) == 2, err2)

    # wigner_spectra and neb_ts: fixture jobs (see this module's docstring).
    wigner_id = _write_fixture_source_job("wigner_spectra", "ensemble_xyz", n_frames=4)
    geoms3, err3 = _resolve_batch_geometries(wigner_id)
    check("wigner_spectra source (ensemble_xyz) resolves", err3 is None and len(geoms3 or []) == 4, err3)

    neb_id = _write_fixture_source_job("neb_ts", "neb_frames", n_frames=5)
    geoms4, err4 = _resolve_batch_geometries(neb_id)
    check("neb_ts source (neb_frames) resolves", err4 is None and len(geoms4 or []) == 5, err4)

    print("\n== _resolve_batch_geometries: an unsupported source task is refused, not guessed ==")
    sp_id = mgr.submit(JobSpec(task="single_point", subtype="gs", method="hf", engine="pyscf",
                               molecule=WATER, params={"basis": "sto-3g"}))
    _wait_terminal([sp_id])
    geoms5, err5 = _resolve_batch_geometries(sp_id)
    check("a plain single_point job is refused as a batch source", geoms5 is None and err5 is not None, err5)
    check("the refusal names every accepted source task",
          err5 is not None and all(t in err5 for t in
                                    ("geometry_set", "pes_1d", "interp_pes", "wigner_spectra", "neb_ts")),
          err5)

    geoms6, err6 = _resolve_batch_geometries("no-such-job-id")
    check("a bad source job id refuses cleanly, not a crash", geoms6 is None and err6 is not None, err6)


def check_frame_tagged_source() -> None:
    print("\n== validate_draft: 3+ tagged molecule-panel frames as a batch source ==")
    stretched = {**WATER, "coords": [[c[0] + 0.2, c[1], c[2]] for c in WATER["coords"]]}
    frames = [
        {"id": "f1", "molecule": WATER, "description": "water"},
        {"id": "f2", "molecule": stretched, "description": "water stretched"},
        {"id": "f3", "molecule": WATER, "description": "water again"},
    ]
    draft = {
        "task": "batch", "subtype": "", "method": "hf", "engine": "pyscf",
        "params": {"basis": "sto-3g", "child_task": "single_point"},
    }
    v = validate_draft(draft, {"molecule_frames": frames})
    check("3 frames on screen: draft reaches ready with no source_job_id given",
          v.status == "ready", v.status)
    check("_frame_geometries carries all 3, in panel order",
          len(v.draft["params"].get("_frame_geometries") or []) == 3,
          v.draft["params"].get("_frame_geometries"))
    check("the note names every frame's own description, not just a count",
          all(f["description"] in " ".join(v.notes) for f in frames), v.notes)

    v_two = validate_draft(draft, {"molecule_frames": frames[:2]})
    check("only 2 frames: not enough to auto-adopt, asks for source_job_id instead",
          v_two.status == "incomplete" and v_two.asking_for == "source_job_id", v_two.status)
    check("the question also mentions the tagging alternative",
          "molecule panel" in (v_two.ask_user_exactly or ""), v_two.ask_user_exactly)

    draft_with_job = {
        "task": "batch", "subtype": "", "method": "hf", "engine": "pyscf",
        "params": {"basis": "sto-3g", "child_task": "single_point", "source_job_id": "some-id"},
    }
    v_job = validate_draft(draft_with_job, {"molecule_frames": frames})
    check("an explicit source_job_id wins over 3+ frames -- no auto-adopt when a job was named",
          "_frame_geometries" not in v_job.draft["params"], v_job.draft["params"])

    print("\n== batch dispatch end to end: 3 frame-tagged geometries (no job on disk at all) ==")
    frame_geometries = [
        {**WATER, "coords": [[c[0] + dx, c[1], c[2]] for c in WATER["coords"]], "name": f"tagged {i}"}
        for i, dx in enumerate((0.0, 0.1, 0.2))
    ]
    mgr = get_job_manager()
    spec, preview, _kb, _notes, batch_note, _kw, warnings, build_error = _build_batch_spec_or_error(
        {}, "pyscf", "hf",
        {"basis": "sto-3g", "child_task": "single_point", "_frame_geometries": frame_geometries}, [],
    )
    check("builder returns a spec with no error", spec is not None and build_error is None, build_error)
    check("batch note names the tagged-frame source, not a job id",
          "tagged in the molecule panel" in (batch_note or ""), batch_note)
    spec.task, spec.subtype = "batch", ""

    master_id = mgr.submit_batch(spec, frame_geometries)
    sub_ids = sub_job_ids_of(master_id)
    check("3 children dispatched", len(sub_ids) == 3, str(sub_ids))
    for sid in sub_ids:
        child_spec = read_spec(sid) or {}
        check(f"{sid}: child does not carry the _frame_geometries blob",
              "_frame_geometries" not in child_spec.get("params", {}), child_spec.get("params"))

    statuses = _wait_terminal(sub_ids)
    for sid, status in statuses.items():
        check(f"{sid}: reached completed", status == "completed", status)

    master_status = _drain_to_completion(master_id)
    check("frame-tagged batch master reaches completed",
          master_status is not None and master_status["status"] == "completed", master_status)


def check_draft_validation(gs_id: str) -> None:
    print("\n== validate_draft: child_task is asked, never defaulted ==")
    draft_no_child_task = {
        "task": "batch", "subtype": "", "method": "hf", "engine": "pyscf",
        "params": {"basis": "sto-3g", "source_job_id": gs_id},
    }
    verdict = validate_draft(draft_no_child_task, {})
    check("status is incomplete, not ready", verdict.status == "incomplete", verdict.status)
    check("the question names all four job types",
          verdict.ask_user_exactly is not None
          and all(w in verdict.ask_user_exactly for w in
                  ("single-point", "optimization", "frequencies", "optimization + frequencies")),
          verdict.ask_user_exactly)

    print("\n== validate_draft: reaches 'ready' for each of the four child task families ==")
    for child in ("single_point", "opt", "freq", "opt_freq"):
        draft = {
            "task": "batch", "subtype": "", "method": "hf", "engine": "pyscf",
            "params": {"basis": "sto-3g", "source_job_id": gs_id, "child_task": child},
        }
        v = validate_draft(draft, {})
        check(f"child_task={child}: draft status is ready", v.status == "ready", v.status)

    print("\n== validate_draft: a genuine capability gap is refused, not silently accepted ==")
    # eom_ccsd has no gradient anywhere in this app's capability matrix, so
    # an opt child cannot actually run -- this is exactly the check that a
    # fixed requires=("energy",) on batch's own TaskDef would have missed,
    # since "energy" is trivially true for every method.
    draft_bad = {
        "task": "batch", "subtype": "", "method": "eom_ccsd", "engine": "orca",
        "params": {"basis": "sto-3g", "source_job_id": gs_id, "child_task": "opt"},
    }
    v_bad = validate_draft(draft_bad, {})
    check("opt child on eom_ccsd (no gradient) is refused",
          v_bad.status == "unavailable", v_bad.status)
    check("the refusal names the real gap (gradient), not a generic denial",
          "gradient" in (v_bad.ask_user_exactly or "").lower(), v_bad.ask_user_exactly)
    # The same method/engine as a single_point child, by contrast, is fine
    # -- eom_ccsd genuinely has 'energy', just not 'gradient'.
    draft_ok = {
        "task": "batch", "subtype": "", "method": "eom_ccsd", "engine": "orca",
        "params": {"basis": "sto-3g", "source_job_id": gs_id, "child_task": "single_point"},
    }
    v_ok = validate_draft(draft_ok, {})
    check("the same method/engine as a single_point child is still fine",
          v_ok.status == "ready", v_ok.status)


def run_batch(gs_id: str, geometries: list, child_task: str, method: str = "hf", engine: str = "pyscf"):
    mgr = get_job_manager()
    spec, preview, _kb, _notes, batch_note, _kw, warnings, build_error = _build_batch_spec_or_error(
        {}, engine, method,
        {"basis": "sto-3g", "source_job_id": gs_id, "child_task": child_task}, [],
    )
    check(f"[{child_task}] builder returns a spec with no error", spec is not None and build_error is None,
          build_error)
    check(f"[{child_task}] preview names job 1 of {len(geometries)}",
          f"job 1 of {len(geometries)}" in (batch_note or ""), batch_note)
    check(f"[{child_task}] batch note names the child task", child_task in (batch_note or ""), batch_note)
    check(f"[{child_task}] no warnings for a well-formed batch", warnings == [], warnings)
    spec.task, spec.subtype = "batch", ""

    master_id = mgr.submit_batch(spec, geometries)
    sub_ids = sub_job_ids_of(master_id)
    check(f"[{child_task}] {len(geometries)} children dispatched", len(sub_ids) == len(geometries), str(sub_ids))
    return master_id, sub_ids


def check_single_point_batch(gs_id: str, geometries: list) -> None:
    print("\n== batch dispatch end to end: single_point/gs (the default-shaped case) ==")
    master_id, sub_ids = run_batch(gs_id, geometries, "single_point")
    for sid in sub_ids:
        child_spec = read_spec(sid) or {}
        check(f"{sid}: child is single_point/gs at the master's method",
              (child_spec.get("task"), child_spec.get("subtype"), child_spec.get("method")) == ("single_point", "gs", "hf"),
              f"got {child_spec.get('task')}/{child_spec.get('subtype')} @ {child_spec.get('method')!r}")
        check(f"{sid}: parent_job_id points at the batch master", child_spec.get("parent_job_id") == master_id)
        check(f"{sid}: child does not carry the batch-only child_task/source_job_id params",
              "child_task" not in child_spec.get("params", {}) and "source_job_id" not in child_spec.get("params", {}),
              child_spec.get("params"))

    statuses = _wait_terminal(sub_ids)
    for sid, status in statuses.items():
        check(f"{sid}: reached completed", status == "completed", status)

    master_status = _drain_to_completion(master_id)
    check("master reaches completed once every child is terminal",
          master_status is not None and master_status["status"] == "completed", master_status)

    result = get_job_manager().result(master_id)
    summary = result["summary"]
    check("summary counts 3 complete, 0 failed",
          summary.get("n_complete") == 3 and summary.get("n_failed", 0) == 0, summary)

    print("\n== master_kind + children pagination reused unmodified for batch ==")
    from server.routes.jobs import _job_row, get_scan_children
    row = _job_row(master_id)
    check("master_kind is 'batch'", row["master_kind"] == "batch", row["master_kind"])

    page = get_scan_children(master_id, None, offset=0, limit=2)
    check("page 1: total is 3", page["total"] == 3, page["total"])
    check("page 1: 2 items", len(page["items"]) == 2, len(page["items"]))
    check("page 1: rows are trimmed (no summary/artifacts/molecule)",
          all("summary" not in r and "artifacts" not in r and "molecule" not in r for r in page["items"]))


def check_freq_batch(gs_id: str, geometries: list) -> None:
    print("\n== batch dispatch end to end: freq (a genuinely different child family) ==")
    master_id, sub_ids = run_batch(gs_id, geometries, "freq")
    for sid in sub_ids:
        child_spec = read_spec(sid) or {}
        check(f"{sid}: child is freq (empty subtype) at the master's method",
              (child_spec.get("task"), child_spec.get("subtype"), child_spec.get("method")) == ("freq", "", "hf"),
              f"got {child_spec.get('task')}/{child_spec.get('subtype')} @ {child_spec.get('method')!r}")

    statuses = _wait_terminal(sub_ids, timeout_s=300)
    for sid, status in statuses.items():
        check(f"{sid}: reached completed", status == "completed", status)

    mgr = get_job_manager()
    for sid in sub_ids:
        result = mgr.result(sid)
        if result and result.get("status") == "completed":
            summary = result.get("summary", {})
            check(f"{sid}: a real frequency summary was produced, not a single-point one",
                  "frequencies_cm-1" in summary and "n_imaginary_frequencies" in summary,
                  sorted(summary.keys()))

    master_status = _drain_to_completion(master_id, timeout_s=60)
    check("freq batch master reaches completed", master_status is not None and master_status["status"] == "completed",
          master_status)


def main() -> int:
    gs_id, geometries = make_geometry_set()

    check_geometry_sources()
    check_frame_tagged_source()
    check_draft_validation(gs_id)
    check_single_point_batch(gs_id, geometries)
    check_freq_batch(gs_id, geometries)

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
