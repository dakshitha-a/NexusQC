#!/usr/bin/env python3
"""A named active space is read against one job's orbital table, and the
draft knows which.

The runner half of this rule is proved in active_02_recorded_active_space.py.
This is the draft half: how `initial_orbitals_job_id` is filled in when
`active_space_orbital_indices` is set, following the rule the user settled on
2026-09-20 (docs/TRACKER.md): a job attached to the message, or one the user
named, is the reference; otherwise, when the conversation holds jobs with
orbital tables, the draft asks which one; only when nothing could have been
read from does `fresh` go through, said on the card. Also: any completed
same-engine job with an orbital table can be a source now (HF and
recommendation jobs included), a source that cannot be used is a question
rather than a silent drop when indices are named, an index beyond the source
table is refused, the source table's occupations are checked against the
claimed electron count, and a draft that has answered the question stays
READY on the re-validation the approval card runs without external checks.

Real fixture jobs in the job store (this checkout's data/jobs), removed in
the `finally` block.

Run:  PYTHONPATH=$PWD python3 tests/backend/active_03_reference_table.py
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import uuid

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import JOB_ATTACH_PREFIX, attached_jobs_this_turn
from app.chemistry.jobs import pyscf_runner
from app.chemistry.jobs.base import JobResult, JobSpec, write_result, write_status
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import (
    FRESH_REFERENCE, _initial_orbitals_problem, _named_space_against_source, validate_draft,
)

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


with contextlib.redirect_stderr(io.StringIO()):
    WATER = resolve_molecule("water").to_dict()
FIELD = "active_space_orbital_indices"
SOURCE = "initial_orbitals_job_id"
CREATED: list[JobSpec] = []


def new_spec(method: str, task: str = "single_point", subtype: str = "gs", engine: str = "pyscf") -> JobSpec:
    spec = JobSpec(method=method, engine=engine, molecule=WATER, task=task, subtype=subtype,
                   job_id=uuid.uuid4().hex[:12])
    CREATED.append(spec)
    return spec


def persist(spec: JobSpec, result: dict, status: str = "completed") -> None:
    write_status(spec.job_id, status, "fixture")
    write_result(JobResult(spec.job_id, status, summary=result["summary"], artifacts=result.get("artifacts", {})))
    (spec.job_dir() / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))


def draft(indices, state: dict, **extra):
    d = {"task": "single_point", "subtype": "gs", "method": "casscf", "engine": "pyscf",
         "params": {"basis": "6-31g", "active_electrons": 4, "active_orbitals": 4,
                    FIELD: indices, **extra}}
    return validate_draft(d, {"molecule": WATER, **state})


def main() -> int:
    print("== which jobs a message attached ==")
    msgs = [HumanMessage("hello"), AIMessage("hi"),
            HumanMessage(JOB_ATTACH_PREFIX.format(jid="aaa111") + " results..."),
            HumanMessage("what about this one"), AIMessage("done"),
            HumanMessage(JOB_ATTACH_PREFIX.format(jid="bbb222") + " results..."),
            HumanMessage(JOB_ATTACH_PREFIX.format(jid="ccc333") + " results..."),
            HumanMessage("swap 26 for 21"), AIMessage("", tool_calls=[])]
    check("the current turn's attachments are the run before the last user text, oldest first",
          attached_jobs_this_turn(msgs) == ["bbb222", "ccc333"], str(attached_jobs_this_turn(msgs)))
    check("an earlier turn's attachment is not this turn's",
          "aaa111" not in attached_jobs_this_turn(msgs))
    check("no attachment, no ids", attached_jobs_this_turn([HumanMessage("x"), AIMessage("y")]) == [])

    try:
        # Fixtures: an HF single point (a table, a molden), a CASSCF job, a
        # recommendation-shaped job, a running job, and an ORCA-engine job.
        hf = new_spec("hf")
        hf_result = pyscf_runner.run_single_point(WATER, {"method": "hf", "basis": "6-31g",
                                                          "_job_dir": str(hf.job_dir())})
        persist(hf, hf_result)
        cas = new_spec("casscf")
        cas_result = pyscf_runner.run_casscf(WATER, {"method": "casscf", "basis": "6-31g",
                                                     "active_electrons": 4, "active_orbitals": 4,
                                                     "n_states": 1, "_job_dir": str(cas.job_dir())})
        persist(cas, cas_result)
        reco = new_spec("cas_reco", task="cas_reco", subtype="recommend")
        reco.job_dir().mkdir(parents=True, exist_ok=True)
        shutil.copy(hf.job_dir() / "orbitals.molden", reco.job_dir() / "orbitals.molden")
        persist(reco, {"summary": {"orbital_table": hf_result["summary"]["orbital_table"],
                                   "active_space_orbital_indices": [4, 5, 6, 7]}})
        running = new_spec("casscf")
        running.job_dir().mkdir(parents=True, exist_ok=True)
        (running.job_dir() / "spec.json").write_text(json.dumps(running.to_dict()))
        write_status(running.job_id, "running", "fixture")
        orca = new_spec("casscf", engine="orca")
        orca.job_dir().mkdir(parents=True, exist_ok=True)
        persist(orca, {"summary": {"orbital_table": hf_result["summary"]["orbital_table"]}})

        print("\n== who can be a source ==")
        check("an HF single point with a table and a molden is a valid source now",
              _initial_orbitals_problem(hf.job_id, "pyscf") is None,
              str(_initial_orbitals_problem(hf.job_id, "pyscf")))
        check("a recommendation job is too", _initial_orbitals_problem(reco.job_id, "pyscf") is None)
        check("a CASSCF job still is", _initial_orbitals_problem(cas.job_id, "pyscf") is None)
        check("a running job is not", "not finished" in (_initial_orbitals_problem(running.job_id, "pyscf") or "")
              or "running" in (_initial_orbitals_problem(running.job_id, "pyscf") or ""))
        check("another engine's job is not, and the message says its numbering means nothing here",
              "mean nothing" in (_initial_orbitals_problem(orca.job_id, "pyscf") or ""))
        check("a job without its orbital file is not",
              "on disk" in (_initial_orbitals_problem(orca.job_id, "orca") or ""),
              str(_initial_orbitals_problem(orca.job_id, "orca")))

        print("\n== the reference rule ==")
        # (a) attached job wins
        v = draft([3, 4, 5, 6], {"attached_job_ids": [cas.job_id], "conversation_job_ids": [hf.job_id, cas.job_id]})
        check("an attached job becomes the reference without a question",
              v.status == "ready" and v.draft["params"].get(SOURCE) == cas.job_id,
              f"{v.status}: {v.ask_user_exactly} {v.draft['params'].get(SOURCE)}")
        check("and the card says the numbers are that job's rows",
              any(cas.job_id in n and "rows" in n for n in v.notes), str(v.notes))
        # (b) candidates but nothing attached: ask, listing them, plus fresh
        v = draft([3, 4, 5, 6], {"conversation_job_ids": [hf.job_id, cas.job_id, running.job_id, orca.job_id]})
        check("with candidates and no pointer, the draft asks which job's table",
              v.status == "incomplete" and v.asking_for == SOURCE, f"{v.status}: {v.asking_for}")
        check("the question lists the usable jobs by label and id, not the running or ORCA ones",
              hf.job_id in (v.ask_user_exactly or "") and cas.job_id in (v.ask_user_exactly or "")
              and running.job_id not in (v.ask_user_exactly or "") and orca.job_id not in (v.ask_user_exactly or ""),
              v.ask_user_exactly)
        check("its options are the candidate ids plus `fresh`",
              set(v.options) == {hf.job_id, cas.job_id, FRESH_REFERENCE}, str(v.options))
        # (c) nothing to read from: fresh, said on the card
        v = draft([3, 4, 5, 6], {"conversation_job_ids": [running.job_id]})
        check("with nothing to read numbers off, the draft goes through against fresh orbitals",
              v.status == "ready" and v.draft["params"].get(SOURCE) == FRESH_REFERENCE,
              f"{v.status}: {v.ask_user_exactly}")
        check("and says so on the card",
              any("fresh SCF orbitals" in n for n in v.notes), str(v.notes))
        # (d) the user answered fresh
        v = draft([3, 4, 5, 6], {"conversation_job_ids": [hf.job_id]}, **{SOURCE: FRESH_REFERENCE})
        check("`fresh` given explicitly is accepted with the same note",
              v.status == "ready" and any("fresh SCF orbitals" in n for n in v.notes), f"{v.status}")
        # (e) an unusable source with indices is a question
        v = draft([3, 4, 5, 6], {"conversation_job_ids": [hf.job_id]}, **{SOURCE: running.job_id})
        check("a source that cannot be used is a question when indices are named, not a drop",
              v.status == "incomplete" and v.asking_for == SOURCE
              and running.job_id in (v.ask_user_exactly or ""), f"{v.status}: {v.ask_user_exactly}")
        v = draft(None, {"conversation_job_ids": [hf.job_id]}, **{SOURCE: running.job_id})
        check("but without indices it is still dropped with a note, as before",
              v.status == "ready" and SOURCE not in v.draft["params"]
              and any("fresh initial guess" in n for n in v.notes), f"{v.status}: {v.notes}")
        # (f) beyond the source table
        n_rows = len(cas_result["summary"]["orbital_table"])
        v = draft([3, 4, 5, n_rows + 5], {}, **{SOURCE: cas.job_id})
        check("an index beyond the source table is refused",
              v.status == "incomplete" and v.asking_for == FIELD and "beyond" in (v.ask_user_exactly or ""),
              f"{v.status}: {v.ask_user_exactly}")
        # (g) occupancy sanity
        refusal, warnings = _named_space_against_source(cas.job_id, [8, 9, 10, 11], 4)
        check("naming four empty rows for a 4-electron space warns about the electron count",
              refusal is None and any("hold 0.00 electrons" in w for w in warnings), str(warnings))
        refusal, warnings = _named_space_against_source(cas.job_id, [1, 2, 3, 8], 4)
        check("leaving a partly occupied active row out warns that it becomes core",
              any("not doubly occupied" in w for w in warnings), str(warnings))
        refusal, warnings = _named_space_against_source(cas.job_id, [4, 5, 6, 7], 4)
        check("the job's own window raises no warning", refusal is None and not warnings, str(warnings))
        # (h) stability under the card's re-validation
        v = draft([3, 4, 5, 6], {"attached_job_ids": [cas.job_id]})
        again = validate_draft(v.draft, {"molecule": WATER}, check_external=False)
        check("a draft that has its reference stays READY when re-validated without external checks",
              again.status == "ready" and again.draft["params"].get(SOURCE) == cas.job_id,
              f"{again.status}: {again.ask_user_exactly}")
        v = draft([3, 4, 5, 6], {})
        again = validate_draft(v.draft, {"molecule": WATER}, check_external=False)
        check("so does one that went through against fresh orbitals",
              again.status == "ready" and again.draft["params"].get(SOURCE) == FRESH_REFERENCE)

        print("\n== the spec the runner gets ==")
        from app.agent.tools import _build_spec_or_error
        built = _build_spec_or_error(
            "single_point", "gs", WATER, "pyscf", "casscf",
            {"basis": "6-31g", "active_electrons": 4, "active_orbitals": 4,
             FIELD: [3, 4, 5, 6], SOURCE: FRESH_REFERENCE})
        spec_built, error = built[0], built[-1]
        check("`fresh` never reaches a runner: the built spec has no source parameter",
              error is None and spec_built is not None and SOURCE not in spec_built.params
              and spec_built.params.get(FIELD) == [3, 4, 5, 6],
              f"{error} {getattr(spec_built, 'params', None)}")
    finally:
        for spec in CREATED:
            shutil.rmtree(spec.job_dir(), ignore_errors=True)
        print(f"  cleaned up {len(CREATED)} fixture job(s)")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
