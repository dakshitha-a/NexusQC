"""Resolving "job X's geometry" to a single molecule dict.

Pulled out of app/agent/tools.py (where it was written for P9.2's
geometry_parameters tool) so app/chemistry/registry2/elicitation.py can
reuse it too, for P9.3's source_geometry_job_id: elicitation.py is
deliberately independent of the agent layer (see validate_draft's own
docstring), so a function it needs has to live at the chemistry-jobs layer,
not the agent layer, regardless of which caller reached it first.
"""
from __future__ import annotations

from typing import Optional

from app.chemistry.jobs.base import get_job_manager, read_spec

# Tasks with no single well-defined geometry: a master job over several
# points/frames (pes_1d, interp_pes, geometry_set, wigner_spectra, batch),
# a blind text input whose geometry is embedded in raw text rather than a
# structured molecule dict, and neb_ts, which has three meaningfully
# different geometries (reactant/product/TS) and no single one of them is
# "the" geometry by default. Note that a master job's own spec.molecule is
# NOT an empty placeholder -- pes_1d/interp_pes store `images[0]`/
# `geometries[0]` there for JobSpec round-tripping, a real but arbitrary
# single point of the whole scan -- so this has to be checked by task
# membership, never inferred from whether spec.molecule happens to be
# truthy.
ORDERED_TABLE_TASKS = {"pes_1d", "interp_pes", "geometry_set"}
HISTOGRAM_TASKS = {"wigner_spectra", "batch"}
NO_SINGLE_GEOMETRY_TASKS = ORDERED_TABLE_TASKS | HISTOGRAM_TASKS | {"blind", "neb_ts"}


def resolve_single_completed_geometry(job_id: str) -> tuple[Optional[dict], Optional[str]]:
    """(molecule, error) for a plain (non-master) completed job -- its
    optimized_molecule if it produced one, else its input molecule. Refuses
    outright for a task with no single well-defined geometry
    (NO_SINGLE_GEOMETRY_TASKS) rather than silently picking one of several."""
    spec = read_spec(job_id)
    if spec is None:
        return None, f"No such job: {job_id}."
    task = spec.get("task") or ""
    if task in NO_SINGLE_GEOMETRY_TASKS:
        return None, (
            f"Job {job_id} (task={task}) has more than one geometry -- tag a specific frame/point instead "
            f"of the job itself, or use geometry_parameters for the whole path/ensemble."
        )
    result = get_job_manager().result(job_id)
    if result is None:
        return None, f"No such job: {job_id}."
    if result.get("status") != "completed":
        return None, f"Job {job_id} is not completed yet (status: {result.get('status')}) -- cannot report its geometry."
    summary = result.get("summary") or {}
    molecule = summary.get("optimized_molecule")
    if not molecule:
        molecule = spec.get("molecule")
    if not molecule:
        return None, f"Job {job_id} has no geometry recorded."
    return molecule, None
