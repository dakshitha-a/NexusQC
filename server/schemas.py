"""Pydantic request bodies for the API. Response shapes are deliberately
left as plain dicts (returned straight from app/ functions or built ad hoc
in the route) rather than modeled here -- the underlying data (job specs,
KB source lists, LangChain messages) doesn't have a fixed schema stable
enough to be worth duplicating in Pydantic on the way out, and FastAPI
already serializes plain dicts/lists to JSON correctly without one.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CreateThreadIn(BaseModel):
    label: Optional[str] = None


class RenameThreadIn(BaseModel):
    label: str


class SetPinnedIn(BaseModel):
    pinned: bool


class MessageIn(BaseModel):
    text: str
    # job_ids the user attached via the Job Manager's "Attach to prompt"
    # action -- see server/routes/chat.py's _run_turn for how these get
    # turned into extra context messages ahead of the user's own text.
    job_ids: list[str] = []
    # A molecule_frames id (see app/agent/state.py) the user attached via
    # the molecule panel's "Attach to prompt" action -- see _run_turn for
    # how this becomes the active molecule for this turn.
    frame_id: Optional[str] = None
    # plot_ids the user attached via the Plots panel. Handled by _run_turn
    # exactly like job_ids: each becomes one synthetic context message ahead
    # of the user's own text, carrying the plot's spec and the numbers it
    # drew (the model cannot see the image).
    plot_ids: list[str] = []


class MoleculeBuildIn(BaseModel):
    # An MDL molfile (V2000/V3000) exported from the 2D sketcher --
    # RDKit reads topology/charges/stereo from it and discards its 2D
    # coordinates (see app.chemistry.molecule.molecule_from_molblock).
    molblock: str
    charge: Optional[int] = None
    multiplicity: Optional[int] = None


class AttachUploadIn(BaseModel):
    # The id of a previously-uploaded .xyz file (server/routes/uploads.py)
    # to attach into this conversation -- see server/routes/chat.py's
    # attach_upload for what happens next (1/2 geometries become frames,
    # 3+ become a geometry_set job).
    upload_id: str


class TagJobFrameIn(BaseModel):
    # Pulls one geometry out of a job whose result carries a path_xyz
    # artifact (a geometry_set, or any pes_1d/interp_pes/wigner_spectra
    # master) and attaches it as the active molecule frame -- see
    # server/routes/chat.py's tag_job_frame. 1-based, matching this app's
    # atom-numbering convention for anything a user sees.
    job_id: str
    frame_index: int


class RenameJobIn(BaseModel):
    label: str


class CreateProjectIn(BaseModel):
    # A project archive: a named bundle of jobs, see
    # app/projects/registry.py. job_ids is optional so the same route
    # serves both "make an empty project" and the common gesture of
    # selecting rows in the job manager and filing them in one go.
    name: str
    description: str = ""
    job_ids: list[str] = []


class UpdateProjectIn(BaseModel):
    # Both optional so a rename does not have to restate the description.
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectJobsIn(BaseModel):
    job_ids: list[str]


class RenderPlotIn(BaseModel):
    kind: str  # "optimization_energy" | "uvvis_inline" | "ir_spectrum_inline" -- see server/routes/jobs.py's render_plot


class JobApprovalIn(BaseModel):
    approved: bool
    input_text: Optional[str] = None


class CreateShareIn(BaseModel):
    # kind is validated against the resource_shares CHECK constraint at the
    # route rather than as a Literal here, so the error is one message the
    # user can read rather than a pydantic union report.
    kind: str
    resource_id: str
    to_user_id: str
    note: str = ""
