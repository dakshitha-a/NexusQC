#!/usr/bin/env python3
"""A named active space means positions in the table it was read from, and
every CASSCF-family result records which of its own orbitals were active.

This reproduces, on water, the three mechanisms found in a real uracil
conversation (docs/TRACKER.md, September 2026) and proves each is closed:

1. Nothing recorded the active window. A default-space CASSCF job's result
   carried no list of its active orbitals, so "swap orbital 26 for 21" had
   nothing to edit. Every result now carries `active_orbital_window`.
2. Named indices were applied to a fresh SCF's canonical orbitals even when
   the numbers had been read off an earlier job's natural-orbital table, a
   different ordering. With `initial_orbitals_job_id` naming the source, the
   starting active block is now exactly the source's table columns.
3. Even with a source, pyscf's `project_init_guess` kept only the source's
   core+active columns and rebuilt the rest from the fresh SCF, so a source
   index in the virtual block (the uracil pi* at row 37) could never be
   honoured. The source's columns are now sorted BEFORE projection, and a
   named virtual index arrives in the starting active block intact.

Plus the record itself: per-orbital retained weights against the reference,
a warning when the optimiser rotates a requested orbital out (exercised
deterministically on constructed matrices, since a real optimisation is
free to keep everything), and the dominant transitions named in the rows
of the natural-orbital table rather than in the pseudo-canonical ordering
the optimisation ran in.

Real runner calls, real files: each fixture job is run through the public
run_* function into the job store (this checkout's data/jobs), read back
through the same molden a later process would read, and removed in the
`finally` block whatever happened.

Water/6-31G rather than STO-3G: a CAS(4,4) on STO-3G leaves no occupied
orbital outside the active space and only two virtuals, so no index can
sit in the source's core or virtual blocks and mechanisms 2 and 3 cannot
be told apart from the default.

Run:  PYTHONPATH=$PWD python3 tests/backend/active_02_recorded_active_space.py
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid

import numpy as np
from pyscf import scf
from pyscf.tools import molden

from app.chemistry.jobs import active_space, pyscf_runner
from app.chemistry.jobs.active_space import RETAINED_WEIGHT_THRESHOLD
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


WATER = resolve_molecule("water").to_dict()
BASIS = "6-31g"
CAS = {"active_electrons": 4, "active_orbitals": 4}
NAMED = [4, 5, 7, 8]  # non-contiguous on purpose: HF row 6 is skipped
CREATED: list[JobSpec] = []


def new_spec(method: str = "casscf", task: str = "single_point", subtype: str = "gs") -> JobSpec:
    spec = JobSpec(method=method, engine="pyscf", molecule=WATER, task=task, subtype=subtype,
                   job_id=uuid.uuid4().hex[:12])
    CREATED.append(spec)
    return spec


def persist(spec: JobSpec, result: dict) -> None:
    """Persists a real completed job's spec/status/result to the job store,
    the way p8_01_orbital_reuse.py does, so a later runner reads the
    source exactly as it would a job submitted through JobManager."""
    write_status(spec.job_id, "completed", "fixture")
    write_result(JobResult(spec.job_id, "completed", summary=result["summary"], artifacts=result["artifacts"]))
    (spec.job_dir() / "spec.json").write_text(json.dumps(spec.to_dict(), indent=2))


def source_columns(spec: JobSpec, indices: list[int]) -> np.ndarray:
    """The named columns of a job's own molden, 1-based, as the user sees them."""
    _mol, _e, mo, _occ, _irrep, _spins = molden.load(str(spec.job_dir() / "orbitals.molden"))
    return np.asarray(mo)[:, [i - 1 for i in indices]]


def starting_block(params: dict) -> tuple[np.ndarray, np.ndarray, object]:
    """The active block a run_casscf call would start from, before kernel()."""
    mol = pyscf_runner.build_mole(WATER, BASIS)
    mf = scf.RHF(mol)
    mf.kernel()
    mc = pyscf_runner._build_casscf(mf, 4, 4, 1, None, pyscf_runner.CASSCF_CONV_TOL_ENERGY)
    initial = pyscf_runner._apply_orbital_choices(mc, params)
    return initial.coeff, mf.get_ovlp(), initial


def diag_overlaps(a: np.ndarray, b: np.ndarray, s: np.ndarray) -> list[float]:
    """|<a_i|b_i>| for matching columns: 1 means the same orbital."""
    return [abs(float(a[:, i] @ s @ b[:, i])) for i in range(a.shape[1])]


def main() -> int:
    # =====================================================================
    print("== the mapping on constructed matrices, including a rotated-out orbital ==")
    # =====================================================================
    eye = np.eye(6)
    c_init = eye[:, [0, 1, 2]]
    # The third starting orbital is replaced by a fifth basis function; the
    # first two are kept, one of them rotated into a 50/50 pair.
    c_final = np.column_stack([
        (eye[:, 0] + eye[:, 1]) / np.sqrt(2), (eye[:, 0] - eye[:, 1]) / np.sqrt(2), eye[:, 4]])
    m = active_space.overlap_mapping(c_init, c_final, [10, 11, 12], s_cross=eye)
    check("row sums are rotation-invariant: the rotated pair still scores 1 each",
          abs(m.per_initial[10] - 1) < 1e-12 and abs(m.per_initial[11] - 1) < 1e-12, str(m.per_initial))
    check("the replaced orbital scores 0", abs(m.per_initial[12]) < 1e-12)
    summary: dict = {}
    table = [{"index": i, "occupancy": 0.0} for i in range(1, 7)]
    active_space.annotate(summary, table, ncore=2, ncas=3, requested=[10, 11, 12],
                          reference_job_id="abc123def456", mapping=m)
    check("the window is ncore+1..ncore+ncas", summary["active_orbital_window"] == [3, 4, 5])
    check("rows in the window are flagged active and the rest are not",
          [r["active"] for r in table] == [False, False, True, True, True, False])
    check("the warning names the lost orbital, the reference table and the row that replaced it",
          "orbital 12 kept weight 0.00" in summary.get("active_space_warning", "")
          and "abc123def456" in summary["active_space_warning"]
          and "final active orbital 5" in summary["active_space_warning"],
          summary.get("active_space_warning"))
    check("the threshold that decides it is the module's own",
          all(w >= RETAINED_WEIGHT_THRESHOLD for k, w in m.per_initial.items() if k != 12))
    summary2: dict = {}
    active_space.annotate(summary2, [dict(r) for r in table], ncore=2, ncas=3,
                          mapping=active_space.overlap_mapping(c_init, c_init, [1, 2, 3], s_cross=eye))
    check("no warning when everything is retained", "active_space_warning" not in summary2)
    check("without a named list the echo key is absent and the window is still there",
          "active_space_orbital_indices" not in summary2 and summary2["active_orbital_window"] == [3, 4, 5])

    try:
        # =================================================================
        print("== job A: CASSCF(4,4)/6-31G on water, named [4,5,7,8] against its own fresh SCF ==")
        # =================================================================
        a = new_spec()
        a_params = {"method": "casscf", "basis": BASIS, **CAS, "n_states": 1,
                    "active_space_orbital_indices": NAMED, "_job_dir": str(a.job_dir())}
        a_result = pyscf_runner.run_casscf(WATER, a_params)
        sa = a_result["summary"]
        persist(a, a_result)
        check("A converged", sa["converged"])
        check("A records its own active window as the contiguous block after ncore",
              sa["active_orbital_window"] == [4, 5, 6, 7], str(sa.get("active_orbital_window")))
        check("A echoes the named list under its original key", sa["active_space_orbital_indices"] == NAMED)
        check("A's reference is its own fresh SCF (no source job)", sa["initial_orbitals_source_job_id"] is None)
        flags = {r["index"]: r["active"] for r in sa["orbital_table"]}
        check("exactly the window rows are flagged active",
              [i for i, f in flags.items() if f] == [4, 5, 6, 7], str(flags))
        weights = {int(k): v for k, v in sa["reference_orbital_weights"].items()}
        check("weights are reported for exactly the named orbitals", sorted(weights) == NAMED, str(weights))
        check("the two occupied named orbitals are retained (weight above 0.95)",
              weights[4] > 0.95 and weights[5] > 0.95, str(weights))
        check("every active row carries a reference index and weight",
              all("reference_index" in r and "reference_weight" in r
                  for r in sa["orbital_table"] if r["active"]))
        check("no HOMO/LUMO on a natural table, with the reason recorded",
              "homo_index" not in sa and "frontier_orbitals_unavailable" not in sa,
              "the runner leaves the frontier to facts.canonicalize; see the check below")
        from app.chemistry.jobs.facts import canonicalize
        canon = canonicalize(dict(sa), a.to_dict())
        check("facts.canonicalize withholds HOMO/LUMO for a natural table and says why",
              "homo_index" not in canon and "homo_lumo_gap_eV" not in canon
              and "natural orbitals" in canon.get("frontier_orbitals_unavailable", ""),
              str({k: canon.get(k) for k in ("homo_index", "orbital_table_kind")}))

        # =================================================================
        print("== mechanism 2: indices read off A's table start from A's orbitals, not the fresh SCF's ==")
        # =================================================================
        want = NAMED
        fresh_block, s_ao, _ = starting_block({"active_space_orbital_indices": want})
        from_a_block, _, initial_b = starting_block({"active_space_orbital_indices": want,
                                                     "initial_orbitals_job_id": a.job_id})
        a_cols = source_columns(a, want)
        ov_a = diag_overlaps(from_a_block, a_cols, s_ao)
        ov_fresh = diag_overlaps(fresh_block, a_cols, s_ao)
        check("with the source named, every starting active orbital IS the source's table column (|overlap| > 0.999)",
              all(o > 0.999 for o in ov_a), str(ov_a))
        check("without the source, the same numbers pick different orbitals (some |overlap| < 0.9)",
              any(o < 0.9 for o in ov_fresh), str(ov_fresh))
        check("the starting labels are the named list and the reference is job A",
              initial_b.labels == want and initial_b.reference_job_id == a.job_id)

        # =================================================================
        print("== mechanism 3: a source VIRTUAL index and a source CORE index survive the projection ==")
        # =================================================================
        # A's table: window 4..7, so 8 and 9 are virtuals and 3 is core.
        hi = [3, 5, 9, 10]
        hi_block, _, _ = starting_block({"active_space_orbital_indices": hi,
                                         "initial_orbitals_job_id": a.job_id})
        ov_hi = diag_overlaps(hi_block, source_columns(a, hi), s_ao)
        check("source core row 3 and virtual rows 9 and 10 arrive in the starting active block intact",
              all(o > 0.999 for o in ov_hi), str(ov_hi))
        try:
            starting_block({"active_space_orbital_indices": [3, 5, 9, 99],
                            "initial_orbitals_job_id": a.job_id})
            check("an index beyond the source table is refused", False)
        except RuntimeError as exc:
            check("an index beyond the source table is refused", "beyond job" in str(exc), str(exc))

        # =================================================================
        print("== job B: the public runner with the source named, end to end ==")
        # =================================================================
        b = new_spec()
        b_params = {"method": "casscf", "basis": BASIS, **CAS, "n_states": 1,
                    "active_space_orbital_indices": want, "initial_orbitals_job_id": a.job_id,
                    "_job_dir": str(b.job_dir())}
        b_result = pyscf_runner.run_casscf(WATER, b_params)
        sb = b_result["summary"]
        persist(b, b_result)
        check("B converged", sb["converged"])
        check("B's reference is job A", sb["initial_orbitals_source_job_id"] == a.job_id)
        check("B's window is its own contiguous block", sb["active_orbital_window"] == [4, 5, 6, 7])
        wb = {int(k): v for k, v in sb["reference_orbital_weights"].items()}
        check("B reports a weight for each of A's named rows", sorted(wb) == want, str(wb))
        # [4,5,7,8] drops A's main correlating orbital (row 6, the one with
        # the 0.003 occupation) for a virtual, and the optimiser is free to
        # undo that: on this host it rotates row 4 out entirely. That is the
        # warning's whole reason to exist, on a real run rather than the
        # constructed one above. The assertion is the consistency of the
        # record, not the particular number, which a different pyscf could
        # move.
        lost = [k for k, w in wb.items() if w < RETAINED_WEIGHT_THRESHOLD]
        check("a weight below the threshold comes with a warning naming that orbital, and none otherwise",
              (bool(lost) == ("active_space_warning" in sb))
              and all(f"orbital {k} kept weight" in sb.get("active_space_warning", "") for k in lost),
              f"weights={wb} warning={sb.get('active_space_warning')!r}")
        print(f"       B's weights against A's table: {wb}")

        # The converged window of A, re-requested off A's table: nothing to
        # improve, so everything is retained and nothing is said.
        b2 = new_spec()
        b2_params = {"method": "casscf", "basis": BASIS, **CAS, "n_states": 1,
                     "active_space_orbital_indices": [4, 5, 6, 7], "initial_orbitals_job_id": a.job_id,
                     "_job_dir": str(b2.job_dir())}
        sb2 = pyscf_runner.run_casscf(WATER, b2_params)["summary"]
        wb2 = {int(k): v for k, v in sb2["reference_orbital_weights"].items()}
        check("re-requesting A's own converged window keeps every orbital (each weight above 0.95)",
              all(w > 0.95 for w in wb2.values()) and "active_space_warning" not in sb2, str(wb2))
        check("and reproduces A's energy",
              abs(sb2["casscf_energy_hartree"] - sa["casscf_energy_hartree"]) < 1e-6,
              f"{sb2['casscf_energy_hartree']} vs {sa['casscf_energy_hartree']}")
        check("`fresh` as the source means no source, and is normalised to null in the result",
              pyscf_runner._reference_job_id({"initial_orbitals_job_id": "fresh"}) is None)

        # =================================================================
        print("== state average and L-PDFT: the record exists and transitions name table rows ==")
        # =================================================================
        c = new_spec(subtype="ee")
        c_params = {"method": "casscf", "basis": BASIS, **CAS, "n_states": 2,
                    "active_space_orbital_indices": want, "initial_orbitals_job_id": a.job_id,
                    "_job_dir": str(c.job_dir())}
        c_result = pyscf_runner.run_casscf(WATER, c_params)
        sc = c_result["summary"]
        check("SA-CASSCF records the window and weights",
              sc["active_orbital_window"] == [4, 5, 6, 7] and len(sc["reference_orbital_weights"]) == 4)
        trans = sc.get("dominant_transitions") or []
        pairs = []
        for t in trans:
            for token in (t or "").replace(",", " ").split():
                if "->" in token:
                    i, j = token.split("->")
                    pairs.append((int(i), int(j)))
        check("the excited state's dominant transition is between rows of the active window",
              pairs and all(i in sc["active_orbital_window"] and j in sc["active_orbital_window"] for i, j in pairs),
              str(trans))
        # The natural-orbital CI is what makes that true: the occupied end of
        # the transition must be a row whose natural occupation is the larger.
        occ = {r["index"]: r["occupancy"] for r in sc["orbital_table"]}
        check("the transition runs from a more-occupied natural orbital to a less-occupied one",
              all(occ[i] > occ[j] for i, j in pairs), str([(i, occ[i], j, occ[j]) for i, j in pairs]))

        d = new_spec(method="lpdft", subtype="ee")
        d_params = {"method": "lpdft", "basis": BASIS, **CAS, "n_states": 2, "ot_functional": "tpbe",
                    "active_space_orbital_indices": want, "initial_orbitals_job_id": a.job_id,
                    "_job_dir": str(d.job_dir())}
        d_result = pyscf_runner.run_lpdft(WATER, d_params)
        sd = d_result["summary"]
        check("L-PDFT records the window, the echo, the reference and the weights",
              sd.get("active_orbital_window") == [4, 5, 6, 7]
              and sd.get("active_space_orbital_indices") == want
              and sd.get("initial_orbitals_source_job_id") == a.job_id
              and len(sd.get("reference_orbital_weights") or {}) == 4,
              str({k: sd.get(k) for k in ("active_orbital_window", "reference_orbital_weights")}))

        # =================================================================
        print("== geometry optimisation: the record comes from the final CASSCF ==")
        # =================================================================
        e = new_spec(task="geometry_optimization")
        e_params = {"method": "casscf", "basis": "sto-3g", **CAS, "n_states": 1,
                    "max_steps": 30, "_job_dir": str(e.job_dir())}
        e_result = pyscf_runner.run_geometry_optimization(WATER, e_params)
        se = e_result["summary"]
        # Water has 10 electrons; CAS(4,4) leaves 3 doubly occupied core
        # orbitals, so the window is rows 4 to 7 whatever the basis.
        check("an optimisation's result carries the window and per-row flags",
              se.get("active_orbital_window") == [4, 5, 6, 7]
              and any(r.get("active") for r in se["orbital_table"]),
              str(se.get("active_orbital_window")))
        check("a default-space job records no echo key but does record the window",
              "active_space_orbital_indices" not in se and "reference_orbital_weights" in se)

        # =================================================================
        print("== the molden a later job reads is the table this job shows ==")
        # =================================================================
        _mol, _e, mo_b, occ_b, _i, _s = molden.load(str(b.job_dir() / "orbitals.molden"))
        check("the molden's occupations are the table's, row for row",
              all(abs(float(occ_b[r["index"] - 1]) - r["occupancy"]) < 1e-6 for r in sb["orbital_table"]))
        check("the molden's columns are orthonormal in the AO metric (a real orbital set, not a dump)",
              np.allclose(np.asarray(mo_b).T @ s_ao @ np.asarray(mo_b), np.eye(np.asarray(mo_b).shape[1]), atol=1e-6))
    finally:
        for spec in CREATED:
            shutil.rmtree(spec.job_dir(), ignore_errors=True)
        print(f"  cleaned up {len(CREATED)} fixture job(s)")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
