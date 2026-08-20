"""Geometry substitution into a hand-edited ORCA/BAGEL input template
(P7.2's interp_pes cascade).

`interp_pes`'s approval card lets a user hand-edit image 0's own literal
input the same way any other ORCA/BAGEL job's card does (see
app/chemistry/jobs/validate.py). For every OTHER master task that edit
applies to exactly the one image it was shown for (pes_1d's
`image0_raw_input`, see JobManager.submit_scan) -- but an interp_pes path
is a sequence of images of the SAME molecule at different geometries, so
whatever the user changed (an extra keyword, a tightened convergence
setting, a different basis) is almost always meant for every image, not
image 0 alone. This module is the mechanical half of that: given the
user's edited text as a TEMPLATE and a target image's own molecule, it
returns the same text with only the geometry block replaced -- every
other line survives byte-for-byte (ORCA) or structurally unchanged
(BAGEL, which is re-serialized JSON rather than a byte-identical file,
since JSON has no canonical "the rest of the file" concept the way a
line-oriented ORCA input does).

Deliberately as narrow as validate.py's own structural checks: this finds
and replaces ONE well-known block shape per engine (the same one this
app's own generated input always uses), not general-purpose ORCA/BAGEL
templating. A template whose geometry block this cannot locate raises
`ValueError` rather than silently leaving a stale geometry in place --
callers (app/agent/tools.py's _finish_submission, at approval time, and
app/chemistry/jobs/scan_orchestrator.py, at dispatch time) both treat that
as a hard stop, never a best-effort partial substitution.
"""
from __future__ import annotations

import json
import re

_ORCA_GEOM_HEADER = re.compile(r"^\*\s*xyz\s+-?\d+\s+\d+\s*$", re.MULTILINE)


def _substitute_orca_geometry(template_text: str, molecule: dict) -> str:
    header = _ORCA_GEOM_HEADER.search(template_text)
    if not header:
        raise ValueError(
            "No '* xyz <charge> <multiplicity>' geometry block found in the template."
        )
    rest = template_text[header.end():]
    close_idx = rest.find("\n*")
    if close_idx == -1:
        raise ValueError("The template's geometry block is missing its closing '*' line.")
    lines = [
        f"{sym:2s} {x: .8f} {y: .8f} {z: .8f}"
        for sym, (x, y, z) in zip(molecule["symbols"], molecule["coords"])
    ]
    new_block = "\n" + "\n".join(lines)
    return template_text[:header.end()] + new_block + rest[close_idx:]


def _substitute_bagel_geometry(template_text: str, molecule: dict) -> str:
    try:
        data = json.loads(template_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
    blocks = (data or {}).get("bagel") if isinstance(data, dict) else None
    if not isinstance(blocks, list):
        raise ValueError("Top-level JSON must be an object with a 'bagel' key containing the list of blocks.")
    mol_block = next((b for b in blocks if isinstance(b, dict) and b.get("title") == "molecule"), None)
    if mol_block is None:
        raise ValueError("No 'molecule' block found in the template.")
    mol_block["geometry"] = [
        {"atom": sym, "xyz": [float(c) for c in xyz]}
        for sym, xyz in zip(molecule["symbols"], molecule["coords"])
    ]
    return json.dumps(data, indent=2)


def substitute_geometry(engine: str, template_text: str, molecule: dict) -> str:
    """`template_text` with its geometry block replaced by `molecule`'s
    atoms -- everything else (keywords, basis, active space, any other
    hand edit) carries through unchanged. Raises ValueError if the
    geometry block cannot be located, never silently no-ops."""
    if engine == "orca":
        return _substitute_orca_geometry(template_text, molecule)
    if engine == "bagel":
        return _substitute_bagel_geometry(template_text, molecule)
    raise ValueError(f"No input template substitution for engine '{engine}'.")
