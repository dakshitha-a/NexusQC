"""Resolving "job X's geometry" to a single molecule dict.

Pulled out of app/agent/tools.py (where it was written for P9.2's
geometry_parameters tool) so app/chemistry/registry2/elicitation.py can
reuse it too, for P9.3's source_geometry_job_id: elicitation.py is
deliberately independent of the agent layer (see validate_draft's own
docstring), so a function it needs has to live at the chemistry-jobs layer,
not the agent layer, regardless of which caller reached it first.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.chemistry import geometry_upload
from app.chemistry.jobs.base import get_job_manager, read_spec
from app.chemistry.registry2.tasks import BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY

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


def resolve_job_geometry(job_id: str, image: Optional[int] = None) -> tuple[Optional[dict], Optional[str]]:
    """(molecule, error) for "job X's geometry", with or without an image.

    Without `image` this is resolve_single_completed_geometry below, which
    is what an ordinary job wants. With one, it is a named point on a
    master's own path: image 1 is the first, counting the way the drawer
    and every message about a path already count (1-based, never 0), so a
    user saying "optimize image 5" and the model passing 5 mean the same
    thing.

    A master addressed with no image is still refused rather than resolved
    to an arbitrary point -- the refusal now says how to name one, since
    before this there was no way to.
    """
    if image is None:
        return resolve_single_completed_geometry(job_id)

    spec = read_spec(job_id)
    if spec is None:
        return None, f"No such job: {job_id}."
    task = spec.get("task") or ""
    if task not in ORDERED_TABLE_TASKS and task != "neb_ts":
        return None, (
            f"Job {job_id} (task={task or 'unknown'}) is a single structure, not a path -- it has no "
            f"image {image}. Drop the image number to use its own geometry."
        )
    frames, row_labels, coordinate_label, error = resolve_ordered_master_frames(job_id, spec)
    if error:
        return None, error
    try:
        index = int(image)
    except (TypeError, ValueError):
        return None, f"An image number must be a whole number; got {image!r}."
    if index < 1 or index > len(frames):
        return None, (
            f"Job {job_id} has {len(frames)} images, numbered 1 to {len(frames)} -- there is no "
            f"image {index}."
        )
    frame = frames[index - 1]
    molecule = {
        "name": f"{frame.name or 'geometry'} (image {index} of job {job_id})",
        "symbols": list(frame.symbols),
        "coords": [list(c) for c in frame.coords],
        # A path's images are geometries only: charge and multiplicity are
        # the master's, not the frame's, and the frame file cannot carry
        # them. Taken from the master's own spec molecule, which is a real
        # point of the same system (see NO_SINGLE_GEOMETRY_TASKS' note on
        # why that field is not an empty placeholder).
        "charge": (spec.get("molecule") or {}).get("charge", 0),
        "multiplicity": (spec.get("molecule") or {}).get("multiplicity", 1),
    }
    return molecule, None


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
        if task in ORDERED_TABLE_TASKS or task == "neb_ts":
            return None, (
                f"Job {job_id} (task={task}) is a path with one geometry per image, so it has no single "
                f"geometry of its own. Name the one you want with source_geometry_image (1 is the first "
                f"image), or use geometry_parameters to compare them all."
            )
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


def resolve_ordered_master_frames(
    job_id: str, spec: dict,
) -> tuple[Optional[list], Optional[list[str]], Optional[str], Optional[str]]:
    """(frames, row_labels, coordinate_label, error) for a pes_1d/
    interp_pes/geometry_set master -- reads geometries from the master's
    own path_xyz artifact (BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY), not
    per-child result.json. P4.3/P7.1 write every image's geometry to that
    one file up front, at submission time, deterministically -- unlike a
    scan image's ENERGY, which fills in only once its sub-job completes,
    the GEOMETRY itself never depends on completion, so this works
    identically on a still-running scan; no pagination or per-child
    fetching needed at all. Row labels are the scan's own
    coordinate_values (pes_1d/interp_pes) or a plain 1-based frame index
    (geometry_set, which has no scan coordinate of its own).

    Lives here rather than in app/agent/tools.py, where it was written for
    P9.2's geometry_parameters tool, for the same reason
    resolve_single_completed_geometry does: the chemistry-jobs layer is
    the lowest one every caller can reach. app/chemistry/jobs/summarize.py
    needs it to put an attached path's geometries in front of the model,
    and summarize.py cannot import the agent layer.
    """
    task = spec.get("task") or ""
    artifact_key = BATCH_GEOMETRY_SOURCE_ARTIFACT_KEY.get(task)
    if not artifact_key:
        return None, None, None, f"Job {job_id} (task={task or 'unknown'}) has no ordered set of geometries."
    result = get_job_manager().result(job_id)
    if result is None:
        return None, None, None, f"No such job: {job_id}."
    path = (result.get("artifacts") or {}).get(artifact_key)
    if not path:
        return None, None, None, f"Job {job_id} has no geometries recorded yet."
    try:
        frames = geometry_upload.parse_multi_frame_xyz(Path(path).read_text())
    except (OSError, ValueError) as e:
        return None, None, None, f"Could not read job {job_id}'s geometries: {e}"
    if not frames:
        return None, None, None, f"Job {job_id} has no geometries to report on."

    summary = result.get("summary") or {}
    coordinate_values = summary.get("coordinate_values")
    if coordinate_values and len(coordinate_values) == len(frames):
        row_labels = [f"{v:.0f}" if float(v).is_integer() else f"{v:.4f}" for v in coordinate_values]
        coordinate_label = summary.get("coordinate", "coordinate")
    else:
        row_labels = [str(i + 1) for i in range(len(frames))]
        coordinate_label = "frame"
    return frames, row_labels, coordinate_label, None
