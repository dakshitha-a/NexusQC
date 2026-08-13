"""Streamlit custom component: a 3Dmol.js molecule viewer + builder with
click-based atom selection (element / bond length / angle / dihedral
readout) and, in "builder" mode, an editing toolbar (add/delete atoms and
bonds, MM cleanup). Hand-rolled frontend (no npm/React build) -- see the
protocol notes at the top of frontend/index.html.
"""
from __future__ import annotations

import os

import streamlit.components.v1 as components

_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
_component_func = components.declare_component("mol_component", path=_frontend_dir)


def mol_component(molecule: dict | None, mode: str = "viewer", height: int = 380,
                   key: str | None = None) -> dict | None:
    """molecule: {"symbols": [...], "coords": [[x,y,z],...], "bonds": [[i,j,order],...]}
    (0-based atom indices in "bonds"; only meaningful in mode="builder" --
    "viewer" mode lets 3Dmol.js perceive bonds from distances itself, same
    as the old render_molecule_html).

    Returns the last value the frontend sent via setComponentValue, or None
    if it hasn't sent one yet this session. Viewer mode never sends a value
    -- its click-to-measure interactivity is entirely self-contained in the
    iframe. Builder mode sends {"action": "cleanup_request" | "use_molecule",
    "nonce": <int>, "symbols": [...], "coords": [...], "bonds": [...]} when
    the user clicks "Clean up" or "Use this molecule"; the nonce increments
    on every send so callers can tell a fresh action from a stale one still
    sitting in the return value across unrelated reruns.
    """
    return _component_func(molecule=molecule, mode=mode, height=height, key=key, default=None)
