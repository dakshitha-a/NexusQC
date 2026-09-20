#!/usr/bin/env python3
"""ORCA and BAGEL record their active window the way PySCF does.

The PySCF half of the active-space record is proved in
active_02_recorded_active_space.py. This runs the two other engines on
water/STO-3G CAS(4,4) and reads their results back:

- ORCA: the window is `n_closed+1 .. n_closed+nact` from the electron count
  the input was built with, cross-checked against the rows whose natural
  occupation is fractional in ORCA's own output. No mapping, since ORCA has
  no way to name active orbitals and its molden does not round-trip
  through pyscf.
- BAGEL: a source CASSCF, then a destination that reuses it (load_ref) and
  names the source's own window as its active space. The destination's
  `reference_orbital_weights` are the overlaps between the source molden's
  named columns and the destination molden's active window, in each
  file's own AO metric. Weights near 1 show that the archive load_ref reads
  and the molden the print block writes order their orbitals the same way,
  which is the one thing about BAGEL's reuse this app could not read off
  either file. BAGEL is slow and has been unstable on this host
  (CLAUDE.local.md), so the live run is bounded: set ACTIVE_04_LIVE_BAGEL=1
  to run it; otherwise the structural checks stand and the run is listed
  as a gap, not a failure.

Every fixture job is removed in the `finally` block.

Run:  PYTHONPATH=$PWD python3 tests/backend/active_04_engine_records.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import uuid

from app.chemistry.jobs import bagel_runner, orca_runner
from app.chemistry.jobs.base import JobResult, JobSpec, write_result, write_status
from app.chemistry.molecule import resolve_molecule

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
CAS = {"active_electrons": 4, "active_orbitals": 4}
CREATED: list[JobSpec] = []


def new_spec(engine: str) -> JobSpec:
    spec = JobSpec(method="casscf", engine=engine, molecule=WATER, task="single_point", subtype="gs",
                   job_id=uuid.uuid4().hex[:12])
    CREATED.append(spec)
    return spec


def persist(spec: JobSpec, result: dict) -> None:
    write_status(spec.job_id, "completed", "fixture")
    write_result(JobResult(spec.job_id, "completed", summary=result["summary"], artifacts=result.get("artifacts", {})))
    (spec.job_dir() / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))


def main() -> int:
    try:
        print("== ORCA: the window and the flags ==")
        o = new_spec("orca")
        result = orca_runner.run_casscf(WATER, {"method": "casscf", "basis": "sto-3g", **CAS, "n_states": 1,
                                                "_job_dir": str(o.job_dir())})
        s = result["summary"]
        check("ORCA CASSCF ran", "casscf_energy_hartree" in s, str(s.get("parse_error")))
        # Water: 10 electrons, 4 active, so 3 closed and the window is 4..7.
        check("the window is rows 4 to 7", s.get("active_orbital_window") == [4, 5, 6, 7],
              str(s.get("active_orbital_window")))
        fractional = [r["index"] for r in s["orbital_table"]
                      if min(abs(r["occupancy"] - n) for n in (0.0, 1.0, 2.0)) > 1e-3]
        check("ORCA's fractional-occupation rows lie inside that window (no disagreement recorded)",
              set(fractional) <= {4, 5, 6, 7} and "active_orbital_window_note" not in s,
              f"fractional={fractional} note={s.get('active_orbital_window_note')}")
        check("exactly the window rows are flagged active",
              [r["index"] for r in s["orbital_table"] if r.get("active")] == [4, 5, 6, 7])
        check("no mapping and no echo on a default-space ORCA job",
              "reference_orbital_weights" not in s and "active_space_orbital_indices" not in s)
        check("the reference is null", s.get("initial_orbitals_source_job_id") is None)

        print("\n== BAGEL: the input names the window and the record reads the moldens ==")
        b_src = new_spec("bagel")
        src_params = {"method": "casscf", "basis": "sto-3g", **CAS, "n_states": 1,
                      "_job_dir": str(b_src.job_dir())}
        text = bagel_runner.build_input_preview("casscf", WATER, {**src_params, "active_space_orbital_indices": [4, 5, 6, 7]})
        check("a named space reaches BAGEL's casscf block as `active`", '"active"' in text and "4," in text)

        # A summary without an export still carries its window. On this
        # host BAGEL's molden block dies in MKL's dsyev after the CASSCF
        # has converged (CLAUDE.local.md; reproduced 2026-09-20: 16
        # macro-iterations to E = -74.98699597, then 'dsyev/pdsyevd failed
        # in Matrix' in the print block), which is how that case was found.
        import tempfile
        empty = tempfile.mkdtemp()
        try:
            summary = {"n_closed_orbitals": 3, "casscf_energy_hartree": -74.987}
            path = bagel_runner._add_orbital_table(summary, empty, params={**src_params, "_job_dir": empty})
            check("with no molden on disk the table is absent but the window is recorded",
                  path is None and "orbital_table" not in summary and summary.get("active_orbital_window") == [4, 5, 6, 7],
                  str(summary))
        finally:
            shutil.rmtree(empty, ignore_errors=True)

        if not os.environ.get("ACTIVE_04_LIVE_BAGEL"):
            print("  [GAP] live BAGEL source/destination run not attempted (set ACTIVE_04_LIVE_BAGEL=1); "
                  "this host's BAGEL/MKL install is slow and has crashed mid-run (CLAUDE.local.md). "
                  "Whether load_ref's archive and the printed molden share an orbital ordering is "
                  "therefore unverified here; the destination's reference_orbital_weights will say "
                  "when it runs.")
        else:
            src_result = bagel_runner.run_casscf(WATER, src_params)
            ss = src_result["summary"]
            check("BAGEL source CASSCF ran", "casscf_energy_hartree" in ss, str(ss.get("parse_error")))
            check("BAGEL records its window", ss.get("active_orbital_window") == [4, 5, 6, 7],
                  str(ss.get("active_orbital_window")))
            check("and flags those rows", [r["index"] for r in ss["orbital_table"] if r.get("active")] == [4, 5, 6, 7])
            check("the flagged rows are the ones BAGEL wrote a zero energy for",
                  all(r["energy_eV"] == 0.0 for r in ss["orbital_table"] if r.get("active")))
            persist(b_src, src_result)
            b_dst = new_spec("bagel")
            dst = bagel_runner.run_casscf(WATER, {**src_params, "_job_dir": str(b_dst.job_dir()),
                                                  "initial_orbitals_job_id": b_src.job_id,
                                                  "active_space_orbital_indices": [4, 5, 6, 7]})
            sd = dst["summary"]
            check("the destination echoes the request and names the source",
                  sd.get("active_space_orbital_indices") == [4, 5, 6, 7]
                  and sd.get("initial_orbitals_source_job_id") == b_src.job_id)
            w = {int(k): v for k, v in (sd.get("reference_orbital_weights") or {}).items()}
            check("weights are reported for the four source rows", sorted(w) == [4, 5, 6, 7], str(w))
            check("re-requesting the source's own window keeps every orbital (weights above 0.9), "
                  "so the archive and the molden order their orbitals the same way",
                  bool(w) and all(v > 0.9 for v in w.values()) and "active_space_warning" not in sd,
                  f"weights={w} warning={sd.get('active_space_warning')!r}")
            print(f"       BAGEL destination weights against the source's table: {w}")
    finally:
        for spec in CREATED:
            shutil.rmtree(spec.job_dir(), ignore_errors=True)
        print(f"  cleaned up {len(CREATED)} fixture job(s)")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
