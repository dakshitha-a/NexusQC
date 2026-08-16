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


class MoleculeBuildIn(BaseModel):
    # An MDL molfile (V2000/V3000) exported from the 2D sketcher --
    # RDKit reads topology/charges/stereo from it and discards its 2D
    # coordinates (see app.chemistry.molecule.molecule_from_molblock).
    molblock: str
    charge: Optional[int] = None
    multiplicity: Optional[int] = None


class RenameJobIn(BaseModel):
    label: str


class RenderPlotIn(BaseModel):
    kind: str  # "optimization_energy" | "uvvis_inline" | "ir_spectrum_inline" -- see server/routes/jobs.py's render_plot


class JobApprovalIn(BaseModel):
    approved: bool
    input_text: Optional[str] = None
