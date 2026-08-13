"""Streamlit custom component: a 3Dmol.js molecule viewer with click-based
atom selection (element / bond length / angle / dihedral readout). Hand-
rolled frontend (no npm/React build) -- see the protocol notes at the top
of frontend/index.html.
"""
from __future__ import annotations

import os

import streamlit.components.v1 as components

_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
_component_func = components.declare_component("mol_component", path=_frontend_dir)


def mol_component(molecule: dict | None, height: int = 380, key: str | None = None) -> None:
    """molecule: {"symbols": [...], "coords": [[x,y,z],...]}. 3Dmol.js
    perceives bonds from interatomic distances itself; there's no explicit
    bond list here. Read-only/self-contained -- all click-to-measure
    interactivity (select up to 4 atoms, element/bond-length/angle/dihedral
    readout, reset on empty-space click) lives entirely in the iframe and
    never round-trips a value back to Python."""
    _component_func(molecule=molecule, height=height, key=key, default=None)
