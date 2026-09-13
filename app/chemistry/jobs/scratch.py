"""Deletes known-safe scratch files from a job's directory once it reaches
a terminal state (completed/failed/cancelled), so ORCA/BAGEL's large
intermediate files (SCF integrals, DIIS vectors, density matrices, grid
data, etc.) don't accumulate indefinitely -- one real ORCA CASSCF/cc-pVDZ
job left ~60MB of these alongside a 77KB output.out.

ORCA's rule is a true allowlist (only files matching a known scratch
pattern are ever candidates -- see _orca_scratch_files). BAGEL's scratch
files have no consistent naming pattern to allowlist (verified: a CASSCF
run left "casscf.log", a Hessian run left "freq.log"), so a completed
BAGEL job instead uses a denylist (everything except the files this app
keeps) -- safe there because a successful run's real artifacts are
already protected via result.json's declared `artifacts`. A failed or
cancelled BAGEL job, and a **blind** one at any outcome, fall back to the
narrower "*.log" pattern instead (see _bagel_scratch_files). Every
candidate, on either engine, is additionally cross-checked against a
protected set (spec/status/result/meta.json, worker.log, and every path
in the job's own declared `artifacts`) before being removed.

Deliberately separate from quota.py's whole-*directory* eviction: this
runs unconditionally once, right after a single job finishes, regardless
of total disk usage; quota.py handles the cross-job 100GB cap.
"""
from __future__ import annotations

from pathlib import Path

from app.chemistry.jobs.base import JOBS_DIR, read_result

_PROTECTED_NAMES = {"spec.json", "status.json", "result.json", "meta.json", "worker.log"}


def _artifact_filenames(result: dict) -> set[str]:
    """Basenames of every file path in the job's own declared artifacts
    (result.json's "artifacts" dict, e.g. raw_output/cubes/molden) --
    walked recursively since some artifacts (cubes) are nested dicts."""
    names: set[str] = set()

    def _walk(node) -> None:
        if isinstance(node, str):
            names.add(Path(node).name)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)

    _walk(result.get("artifacts") or {})
    return names


_ORCA_KEEP_NAMES = {
    "input.inp",  # the approved input text
    # input.gbw is ORCA's own converged-orbitals file (~1MB) -- kept on
    # every ORCA job, not just mo_visualization ones, so orca_plot can
    # lazily render orbitals for any completed ORCA job later (e.g.
    # inspecting orbital character behind a TDDFT/CASSCF excited state),
    # not only jobs explicitly submitted as mo_visualization.
    "input.gbw",
}


def _orca_scratch_files(job_dir: Path) -> list[Path]:
    # ORCA writes every intermediate/auxiliary file under the "input*" stem
    # alongside the files this app actually keeps (see _ORCA_KEEP_NAMES;
    # output.out, the raw_output artifact, never matches this pattern
    # since it doesn't start with "input") -- verified against real runs:
    # a TDDFT single-point (input.cis, input.gbw, input.densities,
    # input.property.txt, ...) and a CASSCF/cc-pVDZ job (additionally
    # input.bas0-5, input.*.tmp SHARK/DIIS/grid scratch, input.hostnames,
    # ~60MB total).
    # rglob, not iterdir, and R-076 is why. A multi-state gradient or a
    # multi-pair NAC runs one full ORCA process per state or pair, each in
    # its own `state_<n>/` or `pair_<a>_<b>/` subdirectory, and this only
    # ever looked at the top level -- so every per-state scratch set
    # survived in full, one copy per state. The module docstring's own
    # measurement is ~60 MB for a single CASSCF/cc-pVDZ run, and those
    # leftovers are billed to the owner's quota and re-walked by every
    # uncached sweep.
    return [f for f in job_dir.rglob("*")
            if f.is_file() and f.name.startswith("input") and f.name not in _ORCA_KEEP_NAMES]


_BAGEL_KEEP_NAMES = {
    "input.json",  # the approved input text
    "bagel.out",
    # orbitals.archive is what BAGEL's save_ref block writes, and every
    # CASSCF/CASPT2-family input this app builds carries that block
    # precisely so a later job can start from these orbitals
    # (bagel_runner._copy_initial_orbitals_archive reads it). Nothing
    # declares it as an artifact, because it is an input to a future job
    # rather than a result of this one, so the denylist below deleted it
    # from every completed BAGEL job and left orbital reuse with no
    # source to reuse -- confirmed on a real structured CASSCF run, which
    # had kept its molden and had no archive at all. Kept unconditionally
    # for the same reason input.gbw is kept on every ORCA job above.
    "orbitals.archive",
}


def _bagel_scratch_files(job_dir: Path, completed: bool, blind: bool) -> list[Path]:
    # Unlike ORCA, BAGEL's scratch/log files have no single consistent
    # naming stem -- verified against real runs: a CASSCF job left
    # "casscf.log" alongside its usual output, a Hessian/frequency job
    # left "freq.log".
    if completed and not blind:
        # Safe to use a broad denylist (everything except the files this
        # app actually uses) ONLY when the job completed AND this app
        # wrote the input: a structured run's real artifacts are already
        # in the protected set via _artifact_filenames, since write_result
        # populated them from a runner that knows what it asked the engine
        # to produce.
        return [f for f in job_dir.iterdir() if f.name not in _BAGEL_KEEP_NAMES]
    # Three cases take the narrow rule instead.
    #
    # On a failed/cancelled run, write_result's `artifacts` defaults to
    # {} -- so a partial run that wrote a real output file before erroring
    # would have nothing protecting it under the broad rule above.
    #
    # A blind job is the same problem for a different reason: the pasted
    # input names its own output files, and this app has no list of what
    # those are, so its runner cannot declare them. A user who wrote
    # `{"title": "print", "file": "orbitals.molden"}` and got an empty
    # directory back is the defect
    # docs/trackers/2026-08-bagel-blind-input.md opens on. The cost of the
    # narrow rule here is that a blind job keeps whatever intermediates
    # BAGEL leaves; that is the trade the failed-run branch already makes,
    # and losing a file the user explicitly asked the engine to write is
    # the worse of the two.
    #
    # Restricted to the one scratch pattern actually observed ("*.log").
    return [f for f in job_dir.iterdir() if f.suffix == ".log"]


def cleanup_scratch_files(job_id: str, engine: str, task: str = "") -> None:
    """No-op for pyscf, which runs in-process and writes nothing to
    job_dir beyond the artifacts it explicitly declares (confirmed: no
    scratch files observed in any real PySCF job directory).

    `task` is read for one thing only: whether this is a blind job, whose
    outputs this app cannot enumerate. See _bagel_scratch_files."""
    if engine not in ("orca", "bagel"):
        return
    job_dir = JOBS_DIR / job_id
    if not job_dir.is_dir():
        return

    result = read_result(job_id) or {}
    protected = _PROTECTED_NAMES | _artifact_filenames(result)
    if engine == "orca":
        candidates = _orca_scratch_files(job_dir)
    else:
        candidates = _bagel_scratch_files(
            job_dir, completed=result.get("status") == "completed", blind=task == "blind")

    for f in candidates:
        if f.name in protected:
            continue
        try:
            if f.is_file():
                f.unlink()
        except OSError:
            continue
