"""Energy units, in one place.

Four units, all of them energy: hartree, eV, nm and cm-1. Three of them are
a scale factor apart; nm is not. A wavelength is inversely proportional to
an energy, so it converts through the reciprocal and a zero energy has no
wavelength at all -- which is also why a RELATIVE energy (a difference
between two energies, referenced to some chosen zero) can be reported in
hartree or eV but not in nm or cm-1: "0.4 eV above the ground state" is a
sentence, "0.4 nm above the ground state" is not.

One table rather than a constant per caller. app/chemistry/spectrum.py had
its own two, which is exactly the duplication that drifts: a plotting path
and a conversion tool disagreeing about what an eV is would be invisible
until someone compared two figures.
"""
from __future__ import annotations

from typing import Optional

# CODATA 2018.
HARTREE_TO_EV = 27.211386245988
EV_TO_NM = 1239.841984
EV_TO_CM1 = 8065.543937

ENERGY_UNITS = ("hartree", "eV", "nm", "cm-1")

# Units that are a difference away from being meaningful. A relative energy
# is a subtraction, and only these two survive it.
RELATIVE_UNITS = ("hartree", "eV")

# What a summary field's own name says its values are in. This project names
# fields with their unit (energies_hartree, excitation_energies_eV,
# frequencies_cm-1), so the unit is usually already written down and asking
# a caller to repeat it is asking them to get it wrong. kcal/mol is listed
# only so a field in it can be REFUSED by name rather than silently read as
# hartree -- it is a real energy unit, but not one of the four here.
_FIELD_SUFFIXES = (
    ("_kcal_mol", "kcal/mol"),
    ("_hartree", "hartree"),
    ("_ev", "eV"),
    ("_nm", "nm"),
    ("_cm-1", "cm-1"),
)


def canonical_unit(unit: str) -> Optional[str]:
    """The spelling this module uses, for any casing/synonym a model might
    reasonably produce. None for anything not one of the four."""
    if not unit:
        return None
    u = str(unit).strip().lower().replace(" ", "").replace("^", "")
    aliases = {
        "hartree": "hartree", "hartrees": "hartree", "ha": "hartree", "eh": "hartree",
        "au": "hartree", "a.u.": "hartree", "atomicunits": "hartree",
        "ev": "eV", "electronvolt": "eV", "electronvolts": "eV",
        "nm": "nm", "nanometer": "nm", "nanometers": "nm", "nanometre": "nm",
        "wavelength": "nm",
        "cm-1": "cm-1", "cm−1": "cm-1", "1/cm": "cm-1", "wavenumber": "cm-1",
        "wavenumbers": "cm-1", "reciprocalcm": "cm-1",
    }
    return aliases.get(u)


def unit_of_field(field: str) -> Optional[str]:
    """The unit a summary field's own name declares, or None if it doesn't.

    Matched against the field path with any index stripped, so
    "excitation_energies_eV[0]" reads the same as "excitation_energies_eV".
    """
    name = (field or "").split("[")[0].strip().lower()
    for suffix, unit in _FIELD_SUFFIXES:
        if name.endswith(suffix):
            return unit
    return None


def to_ev(value: float, unit: str) -> float:
    if unit == "eV":
        return float(value)
    if unit == "hartree":
        return float(value) * HARTREE_TO_EV
    if unit == "nm":
        if value <= 0:
            raise ValueError("a wavelength must be positive to be an energy")
        return EV_TO_NM / float(value)
    if unit == "cm-1":
        return float(value) / EV_TO_CM1
    raise ValueError(f"{unit!r} is not one of {', '.join(ENERGY_UNITS)}")


def from_ev(value_ev: float, unit: str) -> float:
    if unit == "eV":
        return float(value_ev)
    if unit == "hartree":
        return float(value_ev) / HARTREE_TO_EV
    if unit == "nm":
        if value_ev == 0:
            raise ValueError("an energy of zero has no wavelength")
        return EV_TO_NM / float(value_ev)
    if unit == "cm-1":
        return float(value_ev) * EV_TO_CM1
    raise ValueError(f"{unit!r} is not one of {', '.join(ENERGY_UNITS)}")


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """One absolute energy, from one of the four units to another."""
    return from_ev(to_ev(value, from_unit), to_unit)


def convert_values(
    values: list, from_unit: str, to_unit: str, reference_hartree: Optional[float] = None,
) -> tuple[Optional[list], Optional[str]]:
    """(converted, error) for a whole series, keeping None as None.

    With `reference_hartree`, each value is re-expressed as its distance
    ABOVE that absolute energy: subtract in hartree, then convert the
    difference. That is the "plot this in eV relative to -76.412 hartree"
    case, and it is the only case where the target unit is restricted --
    a difference has no wavelength and no wavenumber.

    Returns an error string rather than raising, because every caller here
    is answering a model or a user and wants to say what was wrong.
    """
    src, dst = canonical_unit(from_unit), canonical_unit(to_unit)
    if src is None:
        return None, (f"{from_unit!r} is not an energy unit this converts. "
                      f"Use one of {', '.join(ENERGY_UNITS)}.")
    if dst is None:
        return None, (f"{to_unit!r} is not an energy unit this converts. "
                      f"Use one of {', '.join(ENERGY_UNITS)}.")
    if reference_hartree is not None and dst not in RELATIVE_UNITS:
        return None, (
            f"An energy measured from a reference is a difference between two energies, and a "
            f"difference has no wavelength or wavenumber -- {dst} cannot express one. Ask for "
            f"{' or '.join(RELATIVE_UNITS)} instead, or drop the reference to convert the "
            f"absolute energies themselves."
        )
    out = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        try:
            ev = to_ev(v, src)
            if reference_hartree is not None:
                ev -= float(reference_hartree) * HARTREE_TO_EV
            out.append(from_ev(ev, dst))
        except ValueError as e:
            return None, f"Could not convert {v} {src} to {dst}: {e}."
    return out, None
