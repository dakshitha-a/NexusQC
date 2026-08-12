"""Lightweight static validation for hand-edited ORCA/BAGEL input text.

Run client-side in the Streamlit approval card (see
`app/ui/components.py::render_approval_panel`) before ever resuming the
`submit_job` interrupt, so a typo surfaces immediately with no LLM
round-trip, and again server-side in `submit_job` itself as a defense-in-
depth check. Neither engine offers a "check only"/dry-run mode, so these
are structural and keyword sanity checks, not full grammar validation --
they catch the mistakes a manual edit is actually likely to introduce
(missing block terminators, bad element symbols, malformed JSON), not
every way an input could be chemically wrong.

PySCF has no editable text form (its preview is a synthetic driver
script, not something PySCF itself parses), so there is no validator for
it here -- see CLAUDE.md for why editing is PySCF-only unsupported.
"""
from __future__ import annotations

import json
import re

from pyscf.data.elements import charge as _elem_charge

_ORCA_GEOM_HEADER = re.compile(r"^\*\s*xyz\s+(-?\d+)\s+(\d+)\s*$", re.MULTILINE)
_ORCA_KEYWORD_LINE = re.compile(r"^\s*!", re.MULTILINE)


def _valid_element(symbol: str) -> bool:
    try:
        _elem_charge(symbol)
        return True
    except Exception:
        return False


def _unbalanced_orca_blocks(text: str) -> list[str]:
    """ORCA '%' blocks can be single-line and self-closing ('%pal nprocs 8
    end') or multi-line ('%tddft\\n  nroots 3\\nend') -- only the latter
    needs a separate 'end' line, so a naive count of '%' lines vs 'end'
    lines over-counts self-closing ones as unterminated."""
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("%"):
            if stripped.split()[-1].lower() != "end":
                depth += 1
        elif re.match(r"(?i)^end\b", stripped) and depth > 0:
            depth -= 1
    if depth > 0:
        return [f"{depth} '%...' block(s) appear unterminated (missing a closing 'end' line)."]
    return []


def validate_orca_input(text: str) -> list[str]:
    errors: list[str] = []
    if not text.strip():
        return ["Input is empty."]

    if not _ORCA_KEYWORD_LINE.search(text):
        errors.append("No '!' keyword line found (e.g. '! HF STO-3G') -- ORCA needs one to know what to run.")

    header = _ORCA_GEOM_HEADER.search(text)
    if not header:
        errors.append("No geometry block found (expected a line like '* xyz <charge> <multiplicity>').")
    else:
        rest = text[header.end():]
        end_idx = rest.find("\n*")
        if end_idx == -1:
            errors.append("Geometry block is missing its closing '*' line.")
        block = rest[:end_idx] if end_idx != -1 else rest

        n_atoms = 0
        for line in block.strip().splitlines():
            parts = line.split()
            if not parts:
                continue
            if len(parts) != 4:
                errors.append(f"Malformed geometry line (expected 'Element x y z'): {line!r}")
                continue
            sym, x, y, z = parts
            if not _valid_element(sym):
                errors.append(f"Unrecognized element symbol '{sym}' in geometry block.")
            for coord in (x, y, z):
                try:
                    float(coord)
                except ValueError:
                    errors.append(f"Non-numeric coordinate {coord!r} in geometry line: {line!r}")
            n_atoms += 1
        if n_atoms == 0:
            errors.append("Geometry block has no atoms.")

    errors += _unbalanced_orca_blocks(text)

    return errors


def validate_bagel_input(text: str) -> list[str]:
    if not text.strip():
        return ["Input is empty."]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]

    if not isinstance(data, dict) or "bagel" not in data:
        return ["Top-level JSON must be an object with a 'bagel' key containing the list of blocks."]

    blocks = data["bagel"]
    if not isinstance(blocks, list) or not blocks:
        return ["'bagel' must be a non-empty list of blocks."]

    errors: list[str] = []
    titles = []
    for i, block in enumerate(blocks):
        if not isinstance(block, dict) or "title" not in block:
            errors.append(f"Block {i} is missing a 'title' field.")
            continue
        titles.append(block["title"])

    if "molecule" not in titles:
        errors.append("No 'molecule' block found.")
    else:
        mol_block = next(b for b in blocks if isinstance(b, dict) and b.get("title") == "molecule")
        geometry = mol_block.get("geometry")
        if not geometry or not isinstance(geometry, list):
            errors.append("'molecule' block has no 'geometry' list.")
        else:
            for atom in geometry:
                sym = atom.get("atom") if isinstance(atom, dict) else None
                if not sym or not _valid_element(sym):
                    errors.append(f"Unrecognized or missing element symbol in geometry entry: {atom!r}")
        if "basis" not in mol_block:
            errors.append("'molecule' block is missing a 'basis' field.")

    if len(titles) < 2:
        errors.append("No calculation block found besides 'molecule' (e.g. 'hf', 'casscf').")

    return errors


def validate_input(engine: str, text: str) -> list[str]:
    if engine == "orca":
        return validate_orca_input(text)
    if engine == "bagel":
        return validate_bagel_input(text)
    raise ValueError(f"No editable-input validator for engine '{engine}'")
