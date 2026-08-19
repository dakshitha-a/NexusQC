#!/usr/bin/env python3
"""P2.6/P2B.4 -- jobs are written and read in the v2 taxonomy.

`JobSpec.method` used to do two jobs at once: it was the runner key *and*
the answer to "what kind of calculation is this?". That conflation is why
"a CASSCF single point" and "a CASSCF optimization" were unrelated strings.
P2.6 separated `task`/`subtype` out as the second meaning, leaving `method`
holding the runner key through Phase 2B.1-3. P2B.4 finished the job:
`method` now holds only the level of theory ("hf", "dft", "casscf", ...),
matching what the word means everywhere else in v2 -- which run_*/
build_input_preview function a (task, subtype, method) maps to is derived
fresh, only at dispatch time, by app/chemistry/jobs/dispatch.py's
resolve_runner, and is never stored on the spec at all.

The switch is dangerous in a specific way: nothing errors when it goes
wrong. `spec.method == "wigner_ensemble"` against a v2 spec is not a
crash, it is a comparison that silently stops matching, and the branch it
guards quietly stops running. So the checks here are mostly about
*readers* -- that the ones deciding what a job means consult the task, and
that they still reach the right answer.

The acceptance criterion in OVERHAUL_PLAN.md ("a fixture set of all 14
legacy-type completed jobs renders identically") cannot be met and was
replaced when the Phase 1 clean-slate decision wiped the jobs on disk; see
the note against P2.6 in docs/TRACKER.md. What is asserted instead is
breadth over the v2 taxonomy: one built spec per task the agent can
currently submit.

Run:  PYTHONPATH=$PWD python3 tests/backend/tax_01_v2_specs.py
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid

from app.agent.tools import _spec_from_draft
from app.chemistry.jobs.base import JobSpec, is_master_spec, spec_task
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
STATE = {"molecule": WATER}

CAS = {"active_electrons": 4, "active_orbitals": 4, "n_states": 2}

# One draft per task the agent can submit today. sp/grad and sp/nac are
# absent on purpose: their runners land in Phase 5, and the taxonomy
# refuses them by name rather than by falling through to "unknown".
DRAFTS = [
    ("single_point/gs", {"task": "single_point", "subtype": "gs", "method": "hf",
                         "resolved_engine": "pyscf", "params": {"basis": "sto-3g"}}),
    ("single_point/ee", {"task": "single_point", "subtype": "ee", "method": "dft",
                         "resolved_engine": "pyscf",
                         "params": {"basis": "sto-3g", "functional": "b3lyp",
                                    "n_states": 3}}),
    ("opt/min", {"task": "opt", "subtype": "min", "method": "hf",
                 "resolved_engine": "pyscf",
                 "params": {"basis": "sto-3g", "max_steps": 50}}),
    ("opt/constrained", {"task": "opt", "subtype": "constrained", "method": "hf",
                         "resolved_engine": "pyscf",
                         "params": {"basis": "sto-3g",
                                    "constraints": [{"type": "bond", "atoms": [1, 2],
                                                     "value": 0.98}]}}),
    ("freq", {"task": "freq", "subtype": "", "method": "hf", "resolved_engine": "pyscf",
              "params": {"basis": "sto-3g"}}),
    ("opt_freq", {"task": "opt_freq", "subtype": "", "method": "hf",
                  "resolved_engine": "pyscf", "params": {"basis": "sto-3g"}}),
    ("pes_1d", {"task": "pes_1d", "subtype": "", "method": "hf",
                "resolved_engine": "pyscf",
                "params": {"basis": "sto-3g", "n_points": 3,
                           "coordinate": {"type": "bond", "atoms": [1, 2]},
                           "scan_range": [0.8, 1.2]}}),
    ("cas_reco/autocas", {"task": "cas_reco", "subtype": "autocas", "method": "casscf",
                          "resolved_engine": "pyscf",
                          "params": {"basis": "sto-3g", "n_states": 2}}),
    ("blind", {"task": "blind", "subtype": "", "method": None,
               "resolved_engine": "orca",
               "params": {"raw_input_text": "! HF STO-3G\n* xyz 0 1\nO 0 0 0\n*\n"}}),
]


def main() -> int:
    print("== every submittable task builds a spec carrying its own taxonomy ==")
    specs = {}
    for name, draft in DRAFTS:
        built, error = _spec_from_draft(draft, WATER, STATE)
        if error:
            check(f"{name} builds", False, error)
            continue
        spec = built[0]
        build_error = built[7]
        if spec is None:
            check(f"{name} builds", False, str(build_error))
            continue
        specs[name] = spec
        expected = (draft["task"], draft["subtype"])
        check(f"{name}: spec carries task/subtype",
              (spec.task, spec.subtype) == expected,
              f"got {spec.task!r}/{spec.subtype!r}")
        # P2B.4: spec.method is the level of theory the draft asked for --
        # empty only for "blind", which has none (raw text, no structured
        # method). Never a runner key: dispatch.resolve_runner derives that
        # fresh, at dispatch time, from (task, subtype, method).
        expected_method = draft["method"] or ""
        check(f"{name}: and method is the level of theory, not a runner key",
              spec.method == expected_method,
              f"method={spec.method!r}, expected {expected_method!r}")

    print("\n== the taxonomy survives the round trip to disk ==")
    name, spec = next(iter(specs.items()))
    written = json.loads(json.dumps(spec.to_dict()))
    check("to_dict serializes task and subtype",
          "task" in written and "subtype" in written, f"keys={sorted(written)}")
    check("and JobSpec(**written) reads them back",
          (JobSpec(**written).task, JobSpec(**written).subtype)
          == (spec.task, spec.subtype))

    print("\n== masters are identified by task, not by runner key ==")
    check("a 1-D scan is a master", is_master_spec(specs["pes_1d"].to_dict()))
    check("a single point is not", not is_master_spec(specs["single_point/gs"].to_dict()))
    check("an optimization is not", not is_master_spec(specs["opt/min"].to_dict()))
    check("a blind input is not -- it has no sub-jobs",
          not is_master_spec(specs["blind"].to_dict()))
    # No runner-key fallback: per the no-legacy-compatibility decision, a
    # spec with no task is not expected to exist at all, and is correctly
    # unidentifiable as anything rather than resolved through a second,
    # v1-shaped mechanism.
    check("a task-less spec is not a master (nothing to fall back to)",
          not is_master_spec({"method": "hf"}))
    check("and spec_task reports it honestly as unknown",
          spec_task({"method": "hf"}) == "")

    print("\n== tasks with no runner yet are named, not mishandled ==")
    for name, subtype in (("gradient", "grad"), ("coupling", "nac")):
        _, error = _spec_from_draft(
            {"task": "single_point", "subtype": subtype, "method": "hf",
             "resolved_engine": "pyscf", "params": {"basis": "sto-3g"}}, WATER, STATE)
        check(f"single_point/{subtype} is refused with a reason",
              bool(error) and "Phase 5" in error, f"error={error!r}")

    print("\n== geometry_set is refused as a draft, not a second creation path ==")
    # Phase 3: a geometry_set job is created ONLY by server/routes/chat.py's
    # attach_upload (JobManager.submit_geometry_set), never by the ordinary
    # draft/submit_draft path -- there is no method/engine/params for a
    # model to elicit, and registry2 (task="geometry_set" is master=True,
    # in _NO_MOLECULE) would otherwise let an empty draft reach "ready"
    # with nothing to actually build. If this ever stops being refused,
    # two independent mechanisms create the same kind of job.
    built, error = _spec_from_draft(
        {"task": "geometry_set", "subtype": "", "method": None, "resolved_engine": "pyscf", "params": {}},
        {}, {"molecule": {}},
    )
    check("geometry_set is refused with a reason pointing at attach, not submission",
          built is None and bool(error) and "attach" in error.lower(), f"built={built!r} error={error!r}")

    print("\n== the Wigner source-job check reads the task ==")
    from app.chemistry.registry2.elicitation import _source_frequency_problem

    job_id = f"tax01-{uuid.uuid4().hex[:8]}"
    d = JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    try:
        (d / "spec.json").write_text(json.dumps({
            "job_id": job_id, "method": "hf", "task": "freq", "subtype": "",
            "engine": "pyscf", "molecule": WATER, "params": {}, "label": None,
            "created_at": 0, "parent_job_id": None}))
        (d / "status.json").write_text(json.dumps({"status": "completed", "message": ""}))
        check("a v2 freq job is accepted as a Wigner source",
              _source_frequency_problem(job_id) is None,
              str(_source_frequency_problem(job_id)))

        (d / "spec.json").write_text(json.dumps({
            "job_id": job_id, "method": "hf", "task": "single_point",
            "subtype": "gs", "engine": "pyscf", "molecule": WATER, "params": {},
            "label": None, "created_at": 0, "parent_job_id": None}))
        problem = _source_frequency_problem(job_id)
        check("a v2 single point is refused, and named by its task",
              problem is not None and "single_point" in problem, str(problem))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
