#!/usr/bin/env python3
"""P2B.6 -- the migrated e2e MATRIX and DISALLOWED_PAIRINGS are internally
consistent with registry2, checked without the live stack the e2e harness
itself needs (Ollama, a seeded KB, ORCA/BAGEL licenses).

tests/e2e/_probes.py's MATRIX and DISALLOWED_PAIRINGS were rewritten from
the v1 job_type vocabulary to v2 (task, subtype, method) as part of this
step. Every real e2e run of e2e_08_job_matrix.py/e2e_06_agent_tools.py
needs a full docker-compose stack with a live LLM, which this worktree does
not have -- so this script substitutes what CAN be checked here: registry2's
own capability functions are pure, in-process Python with no external
dependency, and both tables exist specifically to encode what those
functions decide. A row whose migration got the task/subtype/method wrong
is exactly a row this catches.

Two things this does NOT prove, and P2B.7 owns both: that the agent's own
tool-calling actually reaches the approval card the way MATRIX's cells
assume (a live-model question), and that e2e_08_job_matrix.py's
EXPECTED_SUMMARY_KEYS actually match what a completed job's summary
contains (a live-engine-output question, already partly verified for the
single_point/gs case by reading pyscf_runner.py's run_casscf directly --
see this file's own comment -- but not run end to end for every cell).

One finding worth recording explicitly: M23 (neb_ts) needed no special
handling here, but for a reason worth knowing before touching this table
again -- registry2/params.py has no ParamSpec for a NEB-TS end geometry at
all (grep `applies_to=("neb_ts",)`: only `preopt` and `n_images`). The
"needs an end molecule" requirement M23's note refers to is enforced
entirely through conversation-state elicitation (whether a second geometry
is already on screen), not through `missing_required`, so this script
cannot and does not check it -- only a live conversation can.

Run:  PYTHONPATH=$PWD python3 tests/backend/reg2b_03_matrix_v2_taxonomy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "e2e"))
from _probes import DISALLOWED_PAIRINGS, MATRIX  # noqa: E402

from app.chemistry.registry2.params import missing_required  # noqa: E402
from app.chemistry.registry2.tasks import get_task, supports  # noqa: E402

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


def run_matrix() -> None:
    print("== MATRIX: shape ==")
    check("40 cells", len(MATRIX) == 40, str(len(MATRIX)))
    ids = [c[0] for c in MATRIX]
    check("ids are unique", len(ids) == len(set(ids)), str(ids))

    print("\n== MATRIX: every (task, subtype) is a real registry2 task ==")
    for cid, task, subtype, engine, tier, params, note in MATRIX:
        tdef = get_task(task, subtype)
        check(f"{cid} {task}/{subtype} is a registered task", tdef is not None,
              f"get_task({task!r}, {subtype!r}) returned None")

    print("\n== MATRIX: every cell's engine actually supports its (task, subtype, method) ==")
    for cid, task, subtype, engine, tier, params, note in MATRIX:
        method = params.get("method")
        verdict = supports(engine, method, task, subtype)
        check(f"{cid} {task}/{subtype} @ method={method!r} is supported on {engine}",
              verdict.supported, f"reasons={verdict.reasons}")

    print("\n== MATRIX: every cell's declared params satisfy missing_required ==")
    # A cell that is missing a param the row itself was supposed to supply
    # (as opposed to one deliberately left for the agent to elicit -- that
    # is what e2e_18_elicitation.py and E01-E08 test, not this table) means
    # the migration dropped something, most likely the `method` key that
    # v1's job_type string used to carry implicitly.
    for cid, task, subtype, engine, tier, params, note in MATRIX:
        method = params.get("method")
        missing = missing_required(task, subtype, method, engine, params)
        names = sorted(s.name for s in missing)
        if cid == "M24" or cid == "M25":
            # Blind jobs deliberately have empty MATRIX params -- see the
            # cell's own note: "agent composes raw_input_text itself".
            # run_cell never calls prompt_for for these; it hands the model
            # a request to compose the input during the conversation. So
            # `raw_input_text` being the one thing missing here is not a
            # migration gap, it is the cell's entire point.
            check(f"{cid} blind's only gap is raw_input_text (composed by the agent, "
                  f"not supplied by MATRIX)", names == ["raw_input_text"], str(names))
            continue
        check(f"{cid} {task}/{subtype} has everything its own params claim to supply",
              not missing, f"missing={names}")


def run_disallowed() -> None:
    print("\n== DISALLOWED_PAIRINGS: every row is genuinely refused under v2 ==")
    check("9 rows (D08 dropped -- see _probes.py's comment)", len(DISALLOWED_PAIRINGS) == 9,
          str(len(DISALLOWED_PAIRINGS)))
    for did, phrase, method, task, subtype, engine, note in DISALLOWED_PAIRINGS:
        verdict = supports(engine, method, task, subtype)
        check(f"{did} {task}/{subtype} @ method={method!r} is refused on {engine}",
              not verdict.supported, f"unexpectedly supported: {verdict.reasons}")

    print("\n== DISALLOWED_PAIRINGS: D08's drop is itself verified, not assumed ==")
    v = supports("bagel", "hf", "single_point", "gs")
    check("bagel/hf single_point/gs IS supported under v2 (confirms D08 is a real "
          "behavior change, not an oversight)", v.supported, str(v.reasons))


def run_expected_summary_keys_sanity() -> None:
    print("\n== EXPECTED_SUMMARY_KEYS (inlined from e2e_08_job_matrix.py): every "
          "(task, subtype) in MATRIX has an entry ==")
    # Import guarded behind a path insert of its own, since e2e_08 lives
    # beside _probes.py rather than in a package tests/backend can import
    # normally.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "e2e_08_job_matrix",
        Path(__file__).resolve().parent.parent / "e2e" / "e2e_08_job_matrix.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    cells_task_subtype = {(c[1], c[2]) for c in MATRIX}
    for task, subtype in sorted(cells_task_subtype):
        check(f"({task!r}, {subtype!r}) has an EXPECTED_SUMMARY_KEYS entry",
              (task, subtype) in mod.EXPECTED_SUMMARY_KEYS,
              f"missing key {(task, subtype)!r}")

    print("\n== prompt_for/_human_description do not raise for any non-special-cased cell ==")
    for cid, task, subtype, engine, tier, params, note in MATRIX:
        if task in ("blind", "neb_ts"):
            continue  # run_cell builds these prompts itself, not via prompt_for
        try:
            text = mod.prompt_for(task, subtype, engine, params)
            check(f"{cid} prompt_for builds a request", bool(text), "empty string")
        except Exception as e:  # noqa: BLE001
            check(f"{cid} prompt_for builds a request", False, f"{type(e).__name__}: {e}")


def main() -> int:
    run_matrix()
    run_disallowed()
    run_expected_summary_keys_sanity()

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
