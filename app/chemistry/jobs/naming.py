"""Auto-generated, human-meaningful default job labels, e.g.
"H2O CASSCF(6,6)/cc-pVDZ (BAGEL)" -- used by the Job Manager whenever a
job's meta.json has no user-set label (see base.py's read_meta/write_meta);
a user rename always wins over this once one exists.
"""
from __future__ import annotations

from collections import Counter

_METHOD_LABELS = {
    "single_point": "SP",
    "geometry_optimization": "Opt",
    "frequency": "Freq",
    "casscf": "CASSCF",
    "caspt2": "CASPT2",
    "tddft": "TDDFT",
    "eom_ccsd": "EOM-CCSD",
    "mo_visualization": "MO viz",
    "pes_scan": "PES scan",
}


def _formula(symbols: list[str]) -> str:
    """A readable (not strictly canonical Hill-system) chemical formula:
    C first, then H, then everything else alphabetically."""
    counts = Counter(symbols)
    order = []
    if "C" in counts:
        order.append("C")
    if "H" in counts:
        order.append("H")
    order += sorted(s for s in counts if s not in ("C", "H"))
    return "".join(f"{el}{counts[el] if counts[el] > 1 else ''}" for el in order)


def auto_job_name(spec: dict) -> str:
    molecule = spec.get("molecule") or {}
    mol_label = molecule.get("name") or _formula(molecule.get("symbols") or []) or "molecule"

    method = spec.get("method", "job")
    method_label = _METHOD_LABELS.get(method, method)
    params = spec.get("params") or {}

    detail = ""
    if method in ("casscf", "caspt2"):
        ae, ao = params.get("active_electrons"), params.get("active_orbitals")
        if ae and ao:
            detail = f"({ae},{ao})"
    elif method in ("single_point", "geometry_optimization", "frequency", "tddft"):
        qc_method = params.get("method")
        if qc_method == "dft" and params.get("functional"):
            detail = params["functional"]
        elif qc_method:
            detail = qc_method.upper()

    tail = f"{method_label}{detail}"
    basis = params.get("basis")
    if basis:
        tail += f"/{basis}"

    engine = spec.get("engine", "")
    return f"{mol_label} {tail} ({engine.upper()})" if engine else f"{mol_label} {tail}"
