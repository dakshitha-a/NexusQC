"""Deletes known-safe scratch files from a job's directory once it reaches
a terminal state (completed/failed/cancelled), so ORCA/BAGEL's large
intermediate files (SCF integrals, DIIS vectors, density matrices, grid
data, etc.) don't accumulate indefinitely -- one real ORCA CASSCF/cc-pVDZ
job left ~60MB of these alongside a 77KB output.out.

ORCA's rule is a true allowlist (only files matching a known scratch
pattern are ever candidates -- see _orca_scratch_files). BAGEL's scratch
files have no consistent naming pattern to allowlist (verified: a CASSCF
run left "casscf.log", a Hessian run left "freq.log"), so a completed
BAGEL job instead uses a denylist (everything except the two files this
app keeps) -- safe there because a successful run's real artifacts are
already protected via result.json's declared `artifacts`. A failed/
cancelled BAGEL job falls back to the narrower "*.log" pattern instead,
since write_result's `artifacts` is empty on failure and nothing would
protect a partial real output file under the broad rule (see
_bagel_scratch_files). Every candidate, on either engine, is additionally
cross-checked against a protected set (spec/status/result/meta.json,
worker.log, and every path in the job's own declared `artifacts`) before
being removed.

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
    return [f for f in job_dir.iterdir() if f.name.startswith("input") and f.name not in _ORCA_KEEP_NAMES]


def _bagel_scratch_files(job_dir: Path, completed: bool) -> list[Path]:
    # Unlike ORCA, BAGEL's scratch/log files have no single consistent
    # naming stem -- verified against real runs: a CASSCF job left
    # "casscf.log" alongside its usual output, a Hessian/frequency job
    # left "freq.log".
    if completed:
        # Safe to use a broad denylist (everything except the two files
        # this app actually uses) ONLY when the job completed: a
        # successful run's real artifacts are already in the protected set
        # via _artifact_filenames, since write_result populated them.
        return [f for f in job_dir.iterdir() if f.name not in {"input.json", "bagel.out"}]
    # On a failed/cancelled run, write_result's `artifacts` defaults to
    # {} -- so a partial run that wrote a real output file (e.g. a
    # not-yet-implemented molden export failing mid-write) before
    # erroring would have nothing protecting it under the broad rule
    # above. Restrict to the one scratch pattern actually observed
    # ("*.log") instead of risking a file worth debugging.
    return [f for f in job_dir.iterdir() if f.suffix == ".log"]


def cleanup_scratch_files(job_id: str, engine: str) -> None:
    """No-op for pyscf, which runs in-process and writes nothing to
    job_dir beyond the artifacts it explicitly declares (confirmed: no
    scratch files observed in any real PySCF job directory)."""
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
        candidates = _bagel_scratch_files(job_dir, completed=result.get("status") == "completed")

    for f in candidates:
        if f.name in protected:
            continue
        try:
            if f.is_file():
                f.unlink()
        except OSError:
            continue
