#!/usr/bin/env python3
"""Excited-state PES scans: the draft route in, and a real multi-state run.

Two halves, and the second is the one that matters.

The first half checks how a scan draft ever becomes an excited-state scan.
`start_job_draft` takes no `subtype` argument, so the only reliable signal
is the root count: `elicitation._scan_state_subtype` reads `n_states` off
the draft and promotes to the `ee` subtype, with a boundary that differs by
method family (casscf/caspt2 count roots INCLUDING the ground state, so 1 is
a ground-state scan; single-reference methods count excited states ABOVE it,
so 1 is already excited). Get that backwards and an ordinary CASSCF scan
silently becomes a state-averaged one nobody asked for.

The second half submits real scans. A registry that accepts `n_states` and
an orchestrator that dispatches `single_point/ee` children prove nothing on
their own -- the question is whether N images come back with N states each
and whether the plot has more than one line in it. Both a TDDFT scan (where
each child reports a ground-state energy plus excitations) and a CASSCF one
(where each child reports absolute state energies directly) are run, because
`_state_energies_hartree` normalises two different summary shapes into the
one ground-state-first list everything downstream assumes, and only one of
those shapes is exercised by any other script here.

Three real scans, then: PySCF TDDFT, PySCF CASSCF, and ORCA TDDFT. The last
one is not redundant, because ORCA's excited-state runners recorded no
absolute energy at all until this work added one -- the excitation energies
had nothing to be measured from, so every image of an ORCA excited-state
scan normalised to None and the scan drew nothing. BAGEL is left out
deliberately: this host's install is unreliable (see CLAUDE.local.md), not
because the path differs.

This is the slowest script in tests/backend/ by a wide margin: three real
scans of three images each, one of them through ORCA, is roughly fifteen
minutes. That cost is accepted rather than hidden behind a flag, because the
two things most likely to regress here are exactly the things only a real run
shows -- whether a child's summary carries a key this code can read, and
whether the master ends up with more than one series in it. A flag nobody
sets would protect neither. `sec_10_*` is the precedent for excluding a
script from the default run and this deliberately does not follow it.

Run:  PYTHONPATH=$PWD python3 tests/backend/scan_02_excited_state_scans.py
"""
from __future__ import annotations

import sys
import time

from app.agent.tools import _build_scan_images
from app.chemistry.jobs.base import (
    JobSpec, get_job_manager, read_result, read_spec, read_status, sub_job_ids_of,
)
from app.chemistry.jobs.naming import auto_job_name
from app.chemistry.jobs.scan_orchestrator import get_scan_orchestrator
from app.chemistry.jobs.summarize import _format_summary_value
from app.chemistry.molecule import resolve_molecule
from app.chemistry.registry2.elicitation import validate_draft
from app.chemistry.registry2.tasks import engines_supporting
from app.agent.tools import _param_applies

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


def _draft_subtype(method: str, params: dict, molecule: dict, end: dict,
                   subtype: str = "") -> tuple[str, tuple[str, ...], str]:
    """(resolved subtype, notes, status) for an interp_pes draft."""
    draft = {
        "task": "interp_pes", "subtype": subtype, "method": method, "engine": "pyscf",
        "params": {"basis": "sto-3g", "n_points": 3, "_end_molecule": end, **params},
    }
    v = validate_draft(draft, {"molecule": molecule}, check_external=False)
    return v.draft["subtype"], v.notes, v.status


def part1_draft_routing(m: dict, end: dict) -> None:
    print("== A scan's root count decides ground state vs excited state ==")

    sub, notes, status = _draft_subtype("dft", {"functional": "b3lyp"}, m, end)
    check("no root count at all stays a ground-state scan", sub == "", f"got {sub!r}")

    sub, notes, _ = _draft_subtype("dft", {"functional": "b3lyp", "n_states": 3}, m, end)
    check("n_states=3 on TDDFT promotes to the ee subtype", sub == "ee", f"got {sub!r}")
    check("the promotion is said out loud, not silent",
          any("excited states at every point" in n for n in notes), str(notes))

    sub, _, _ = _draft_subtype("dft", {"functional": "b3lyp", "n_states": 1}, m, end)
    check("n_states=1 on TDDFT is already excited (counts states ABOVE ground)",
          sub == "ee", f"got {sub!r}")

    # The regression this guards: 5b rewrites an n_states=0 single-reference
    # ee draft to subtype "gs", and a scan's ground-state key is the BARE
    # subtype. Unguarded it would produce an interp_pes/gs that is not in
    # TASKS at all.
    sub, _, status = _draft_subtype("dft", {"functional": "b3lyp", "n_states": 0}, m, end)
    check("n_states=0 on TDDFT falls back to the bare scan, not a bogus /gs",
          sub == "", f"got {sub!r}")
    check("...and that draft is still routable", status == "ready", f"status={status!r}")

    cas = {"active_electrons": 4, "active_orbitals": 4}
    sub, _, _ = _draft_subtype("casscf", {**cas, "n_states": 1}, m, end)
    check("n_states=1 on CASSCF stays ground state (count INCLUDES ground)",
          sub == "", f"got {sub!r}")

    sub, _, _ = _draft_subtype("casscf", {**cas, "n_states": 3}, m, end)
    check("n_states=3 on CASSCF promotes to ee", sub == "ee", f"got {sub!r}")

    # A model that writes the subtype directly must not reach READY without
    # a root count, or every image runs a one-state calculation.
    sub, _, status = _draft_subtype("dft", {"functional": "b3lyp"}, m, end, subtype="ee")
    check("subtype=ee with no root count is asked for one, not accepted",
          status == "incomplete", f"status={status!r} subtype={sub!r}")


def part1b_the_reported_bug() -> None:
    """The refusal the bug report actually hit.

    Everything in part 1 builds a draft dict and hands it to validate_draft,
    which is one layer below where the symptom lived: `update_job_draft`
    gates each key through `_param_applies` FIRST and returns a refusal
    message without ever calling validate_draft, so a scan draft could not be
    given a root count at all. Checking the promotion logic without checking
    this gate would leave the original report unverified.
    """
    print("\n== n_states can be written onto a scan draft at all ==")
    for task in ("pes_1d", "interp_pes"):
        fresh = {"task": task, "subtype": "", "method": "dft"}
        check(f"a fresh {task} draft accepts n_states",
              _param_applies(fresh, "n_states"),
              "this is the refusal the bug report hit")
        # The model writes both keys in one update_job_draft call, and ONE
        # inapplicable key refuses the whole call. use_tda is scoped to the
        # /ee subtypes, so it must be applicable by the time the draft is
        # excited-state -- and must not be offered before, or every
        # ground-state scan card carries a Tamm-Dancoff row.
        excited = {"task": task, "subtype": "ee", "method": "dft"}
        check(f"an excited-state {task} draft accepts use_tda",
              _param_applies(excited, "use_tda"))
        check(f"a ground-state {task} draft does NOT offer use_tda",
              not _param_applies(fresh, "use_tda"),
              "a linear-response flag on a job that solves no linear response")


def part2_capabilities() -> None:
    print("\n== Routing stays honest about which methods have excited states ==")
    check("CASSCF excited-state scans run on all three engines",
          set(engines_supporting("casscf", "interp_pes", "ee")) == {"pyscf", "orca", "bagel"},
          str(engines_supporting("casscf", "interp_pes", "ee")))
    check("CASPT2 excited-state scans run on BAGEL",
          tuple(engines_supporting("caspt2", "interp_pes", "ee")) == ("bagel",),
          str(engines_supporting("caspt2", "interp_pes", "ee")))
    check("TDDFT excited-state scans run on PySCF and ORCA",
          set(engines_supporting("dft", "interp_pes", "ee")) == {"pyscf", "orca"},
          str(engines_supporting("dft", "interp_pes", "ee")))
    for m in ("mp2", "ccsd"):
        check(f"{m} has no excited-state scan anywhere (no formulation here)",
              engines_supporting(m, "interp_pes", "ee") == (),
              str(engines_supporting(m, "interp_pes", "ee")))
    check("the ground-state scan is untouched by any of this",
          set(engines_supporting("ccsd", "interp_pes", "")) == {"pyscf", "orca"},
          str(engines_supporting("ccsd", "interp_pes", "")))


def part3_labels() -> None:
    print("\n== An excited-state scan is named in words, not as an identifier ==")
    for task, want in (("pes_1d", "PES scan"), ("interp_pes", "Path scan")):
        name = auto_job_name({"task": task, "subtype": "ee", "method": "dft", "engine": "pyscf",
                              "molecule": {"name": "water", "symbols": ["O", "H", "H"]},
                              "params": {"functional": "b3lyp", "basis": "sto-3g"}})
        check(f"{task}/ee reads as {want!r}, not {task!r}",
              want in name and task not in name, name)

    print("\n== Per-image state energies keep their shape for the model ==")
    rendered = _format_summary_value([[-76.02, -75.71], [-76.01, -75.68]])
    check("a list of per-image lists is bracketed, not flattened",
          rendered == "[-76.02, -75.71]; [-76.01, -75.68]", rendered)
    check("a plain list of numbers is unchanged",
          _format_summary_value([-76.02, -76.01]) == "-76.02, -76.01",
          _format_summary_value([-76.02, -76.01]))


def _run_scan(label: str, method: str, params: dict, m: dict, end: dict,
              want_states: int, timeout: int, engine: str = "pyscf") -> None:
    print(f"\n== A real {label} excited-state path scan ==")
    mgr = get_job_manager()
    master = JobSpec(
        task="interp_pes", subtype="ee", method=method, engine=engine,
        molecule=m,
        params={"basis": "sto-3g", "n_points": 3, "interpolation_method": "linear",
                "_scan_start_molecule": m, "_end_molecule": end, **params},
    )
    images, coordinate_values, coordinate_label, _w = _build_scan_images(master.params)
    master_id = mgr.submit_scan(master, images, coordinate_values, coordinate_label)
    sub_ids = sub_job_ids_of(master_id)
    check(f"{label}: 3 sub-jobs dispatched", len(sub_ids) == 3, str(sub_ids))

    for sid in sub_ids:
        spec = read_spec(sid) or {}
        check(f"{label}: {sid} is a single_point/ee child at {method}",
              (spec.get("task"), spec.get("subtype"), spec.get("method"))
              == ("single_point", "ee", method),
              f"got {spec.get('task')}/{spec.get('subtype')} @ {spec.get('method')!r}")
        check(f"{label}: {sid} carries the root count through to the image",
              spec.get("params", {}).get("n_states") == params["n_states"],
              repr(spec.get("params", {}).get("n_states")))

    deadline = time.time() + timeout
    result = {}
    while time.time() < deadline:
        if (read_status(master_id) or {}).get("status") in ("completed", "failed"):
            break
        time.sleep(2)
    status = (read_status(master_id) or {}).get("status")
    result = read_result(master_id) or {}
    check(f"{label}: the master reached completed", status == "completed",
          f"status={status!r} {str(result.get('summary', {}))[:200]}")

    summary = result.get("summary") or {}
    per_image = summary.get("state_energies_per_image") or []
    check(f"{label}: every image reported {want_states} states",
          len(per_image) == 3 and all(s and len(s) == want_states for s in per_image),
          str(per_image)[:300])
    check(f"{label}: state energies are ordered ground state first",
          per_image and all(s and s == sorted(s) for s in per_image), str(per_image)[:300])
    # Three identical images satisfy every check above. This is the one that
    # says the scan actually scanned something: the ground-state curve has to
    # move across the path, and the excited states have to sit above it.
    ground = [s[0] for s in per_image if s]
    check(f"{label}: the ground-state curve varies along the path",
          len(set(round(g, 6) for g in ground)) == len(ground), str(ground))
    check(f"{label}: every excited state lies above its own image's ground state",
          all(all(e > s[0] for e in s[1:]) for s in per_image if s), str(per_image)[:300])
    check(f"{label}: a multi-state plot was rendered",
          "pes_plot" in (result.get("artifacts") or {}),
          str(list((result.get("artifacts") or {}).keys())))


def _stack_is_up() -> bool:
    """Whether a live stack is already advancing scan masters.

    Deliberately a health check against the same base URL the rest of this
    suite uses, rather than looking for a process: the thing that matters is
    whether an api container is watching this checkout's data/jobs, and that
    is exactly what answering on that URL means.
    """
    try:
        import httpx
        from tests.fixtures import BASE_URL
        return httpx.get(f"{BASE_URL}/api/health", verify=False, timeout=5.0).status_code == 200
    except Exception:
        return False


def _stretched(m: dict) -> dict:
    """`m` with one O-H bond pulled out by 25%, as the path's far endpoint.

    Scaling z would be the obvious thing and is silently a no-op: RDKit
    hands back a PLANAR water, every atom at z=0, so a z-scaled "endpoint"
    is the same geometry and all three images come out identical. A scan of
    three identical geometries still passes a naive "N states per image"
    check, with three flat lines -- which is why part 4 also asserts the
    curves actually separate.
    """
    end = dict(m)
    coords = [list(row) for row in m["coords"]]
    ox, oy, oz = coords[0]
    hx, hy, hz = coords[1]
    coords[1] = [ox + (hx - ox) * 1.25, oy + (hy - oy) * 1.25, oz + (hz - oz) * 1.25]
    end["coords"] = coords
    return end


def main() -> int:
    m = resolve_molecule("water").to_dict()
    end = _stretched(m)

    # A scan master is advanced by the ScanOrchestrator, and nothing starts
    # it on import -- server/main.py's lifespan does, which is why the rest
    # of the suite never had to. A script that submits a scan and then waits
    # on its MASTER (rather than only on the child specs, which is all
    # reg2b_02 checks) needs one running somewhere.
    #
    # Exactly one, though. `dispatch_lock` is a module-level threading.Lock,
    # so it serializes two threads in ONE process and does nothing across
    # two -- a script that starts its own while the stack's api container is
    # also watching data/jobs gives two orchestrators that can each read
    # "no children yet" for the same master and each dispatch a full set.
    # So: start one only when there is no live stack to have started it,
    # which is also the honest reading of tests/README.md's contract that
    # this suite runs against a live stack.
    #
    # Worth knowing when this script disagrees with a running stack: the
    # orchestrator holds the summary-building code in memory, so a container
    # running an older image keeps writing masters with ITS version of
    # _state_energies_hartree even while this checkout has a newer one.
    orchestrator = None
    if not _stack_is_up():
        print("  (no live stack detected -- starting a ScanOrchestrator in-process)")
        orchestrator = get_scan_orchestrator()
        orchestrator.start()
    try:
        _run_all(m, end)
    finally:
        if orchestrator is not None:
            orchestrator.stop()

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


def _run_all(m: dict, end: dict) -> None:
    part1_draft_routing(m, end)
    part1b_the_reported_bug()
    part2_capabilities()
    part3_labels()

    # TDDFT: children report energy_hartree + excitation_energies_eV, which
    # _state_energies_hartree turns into a ground-state-first absolute list.
    # n_states=2 excited states, so 3 series including the ground state.
    _run_scan("TDDFT", "dft", {"functional": "b3lyp", "n_states": 2}, m, end,
              want_states=3, timeout=300)

    # CASSCF: children report state_energies_hartree directly, and the count
    # INCLUDES the ground state, so n_states=3 is 3 series. This is also the
    # path that proves resolve_runner's casscf test beating its subtype=="ee"
    # test -- a wrong ordering here runs TDDFT on a CASSCF request.
    _run_scan("CASSCF", "casscf",
              {"n_states": 3, "active_electrons": 4, "active_orbitals": 4}, m, end,
              want_states=3, timeout=600)

    # ORCA TDDFT. Not redundant with the PySCF run above: ORCA's own
    # excited-state runners recorded NO absolute energy at all until this
    # work added one, so every image of an ORCA excited-state scan
    # normalised to None and the whole scan produced an empty plot. This is
    # the only script that would catch that coming back.
    _run_scan("ORCA TDDFT", "dft", {"functional": "b3lyp", "n_states": 2}, m, end,
              want_states=3, timeout=900, engine="orca")


if __name__ == "__main__":
    sys.exit(main())
