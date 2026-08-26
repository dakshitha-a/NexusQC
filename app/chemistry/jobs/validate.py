"""Lightweight static validation for hand-edited ORCA/BAGEL input text.

Called from `submit_draft` itself (`app/agent/tools.py`) before writing an
edited input into `spec.params["_raw_input"]`, so a typo is caught before
a job is actually spawned. Neither engine offers a "check only"/dry-run
mode, so these are structural and keyword sanity checks, not full grammar
validation --
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


# Engines that have an editable input format and therefore a validator.
# PySCF is deliberately absent: its "input" is a synthetic driver script
# standing in for direct API calls, so there is nothing an edit could
# change at execution time (see this module's docstring). Callers that may
# be handed an arbitrary engine should check membership here rather than
# letting validate_input raise.
VALIDATED_ENGINES = frozenset({"orca", "bagel"})


def validate_input(engine: str, text: str) -> list[str]:
    if engine == "orca":
        return validate_orca_input(text)
    if engine == "bagel":
        return validate_bagel_input(text)
    raise ValueError(f"No editable-input validator for engine '{engine}'")


# ---------------------------------------------------------------------------
# Severity classification (F-018)
# ---------------------------------------------------------------------------
#
# Structural validation is deliberately NON-BLOCKING for job_type='custom':
# that job type exists to carry ORCA/BAGEL syntax this validator was never
# built to recognize (%coords blocks, $new_job stacks, a genuine
# `* xyzfile` pointing at a real filename), so hard-blocking on a finding
# would defeat the feature's own premise.
#
# But not every finding is the same kind of claim, and treating them alike
# cost a real job. A `custom` ORCA input was composed with `* xyzfile 0 1`
# (the read-from-external-file form, which expects a filename) followed by
# inline coordinates (the `* xyz` form). The app's own validator diagnosed
# it exactly -- and the job ran anyway, spending 33 seconds of compute to
# produce an opaque "CANNOT OPEN FILE Filename:" error instead of the
# accurate diagnosis already in hand.
#
# So findings are now split by what the validator can actually claim:
#
#   WARNING  "I did not find a construct I know how to look for."
#            Absence is weak evidence on a custom input -- the construct
#            may simply be one of the many this validator does not model.
#            Stays advisory, exactly as before.
#
#   ERROR    "I found this construct and it is malformed."
#            Presence plus a defect is a positive claim, and it is just as
#            true for a custom input as for a generated one. A bad element
#            symbol is a bad element symbol regardless of job_type.
#
# The UI renders the two differently (JobApprovalCard.tsx) so a definite
# defect can no longer look like the routine yellow noise banner.

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

# Messages that report the ABSENCE of an expected construct. Matched on a
# distinctive prefix rather than by re-running the checks, so the message
# text stays the single source of truth and the two can't drift apart.
_ABSENCE_PREFIXES = (
    "No '!' keyword line found",
    "No geometry block found",
    "No 'molecule' block found",
    "No calculation block found",
)

_ORCA_XYZFILE_HEADER = re.compile(r"^\*\s*xyzfile\s+(-?\d+)\s+(\d+)\s*(\S*)\s*$", re.MULTILINE)
_COORD_LINE = re.compile(r"^\s*([A-Za-z]{1,3})\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s*$")


def _orca_xyzfile_contradiction(text: str) -> list[str]:
    """`* xyzfile <charge> <mult> <filename>` reads coordinates from an
    external file. Inline coordinate lines after that header are the
    `* xyz` form instead, so an input containing both is self-
    contradictory -- and ORCA's own failure for it ("CANNOT OPEN FILE
    Filename:") names the symptom rather than the cause.

    This is a positively-detected defect, not an unrecognized construct:
    the header IS recognized here, and what follows it contradicts what it
    means. A legitimate `* xyzfile 0 1 geom.xyz` with no inline
    coordinates is untouched by this check.
    """
    out: list[str] = []
    for m in _ORCA_XYZFILE_HEADER.finditer(text):
        filename = m.group(3)
        rest = text[m.end():]
        end_idx = rest.find("\n*")
        block = rest[:end_idx] if end_idx != -1 else rest
        inline = [ln for ln in block.splitlines() if _COORD_LINE.match(ln)]
        if inline:
            out.append(
                f"'* xyzfile' reads coordinates from an external file, but "
                f"{len(inline)} inline coordinate line(s) follow it. Use '* xyz "
                f"{m.group(1)} {m.group(2)}' for inline coordinates, or give "
                f"'* xyzfile' a filename to read."
            )
        elif not filename:
            out.append(
                "'* xyzfile' is missing its filename argument -- ORCA will fail "
                "with 'CANNOT OPEN FILE'."
            )
    return out


def classify_findings(engine: str, text: str) -> tuple[list[str], list[str]]:
    """Runs the engine's validator and splits its findings into
    (errors, warnings) -- see the block comment above for the rule.

    Used by the `custom` path, where warnings stay advisory but errors are
    surfaced as definite defects. Every other job_type keeps using
    `validate_input` and blocks on any finding at all, since those inputs
    are generated from a standard template and a finding there means
    something broke a previously-valid file.
    """
    findings = list(validate_input(engine, text))
    if engine == "orca":
        findings += _orca_xyzfile_contradiction(text)
    errors, warnings = [], []
    for f in findings:
        (warnings if f.startswith(_ABSENCE_PREFIXES) else errors).append(f)
    return errors, warnings


# --- Active space against the size of the basis ---------------------------


def n_basis_functions(molecule: dict, basis: str) -> int | None:
    """How many basis functions (molecule, basis) has, or None if unknown.

    Built through the same `pyscf_runner.build_mole` every PySCF job uses,
    so BSE references and this app's basis-name spellings resolve exactly as
    they do at run time rather than through a second, drifting
    interpretation. Returns None rather than raising when the pair cannot be
    built at all: an unbuildable molecule is a different problem, already
    reported elsewhere, and a size check is not the place to surface it.

    Deliberately not in registry2: that module states plainly that at draft
    time this app has not built the molecule and does not know how many
    orbitals the basis has. This does build it, which is why it lives here
    with the other engine-facing checks and is called from the job-spec
    builder rather than from elicitation.
    """
    try:
        from app.chemistry.jobs.pyscf_runner import build_mole
        return int(build_mole(molecule, basis).nao)
    except Exception:  # noqa: BLE001 -- see docstring
        return None


def caspt2_virtual_space_problem(
    molecule: dict, basis: str, active_electrons: int, active_orbitals: int,
) -> str | None:
    """Why this CASPT2 request has no virtual space, or None if it has one.

    CASPT2 is a second-order correction *into* the virtual space. When the
    closed and active orbitals between them use every function the basis
    has, there is nothing left to excite into: the amplitude equations are
    empty, and BAGEL dies inside LAPACK rather than saying so
    ("Parameter 9 was incorrect on entry to cblas_dgemm", then
    "dsyev/pdsyevd failed in Matrix").

    Found by the manuscript evaluation battery's A-19 and A-20, where water
    in STO-3G (7 functions) with a CAS(4,4) and 3 closed orbitals used all 7.
    Six trials died this way and were first blamed on this host's documented
    BAGEL/MKL instability -- wrongly, as R-6 running the same method on
    H2CO/cc-pVDZ to completion in the same container then showed. Checked
    before the approval card so the request is refused rather than carded,
    which is the whole argument for having a card.
    """
    n_bf = n_basis_functions(molecule, basis)
    if n_bf is None:
        return None
    n_electrons = sum(_elem_charge(s) for s in molecule["symbols"]) - int(molecule.get("charge", 0))
    n_closed = (n_electrons - int(active_electrons)) // 2
    if n_closed < 0:
        return None  # a malformed active space; caught by its own check
    n_virtual = n_bf - n_closed - int(active_orbitals)
    if n_virtual > 0:
        return None
    return (
        f"{basis} gives this molecule {n_bf} basis functions, and a "
        f"({active_electrons}e, {active_orbitals}o) active space with {n_closed} closed "
        f"orbital(s) uses {n_closed + int(active_orbitals)} of them, leaving "
        f"{max(n_virtual, 0)} virtual orbitals. CASPT2 is a correction into the virtual "
        f"space, so there is nothing for it to correlate into and the engine will fail "
        f"rather than return a result. Use a larger basis set, or a smaller active space."
    )
