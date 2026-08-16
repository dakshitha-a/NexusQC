"""Mechanical "closest-matching exact syntax keyword" suggestions for basis
sets and DFT functionals, surfaced to the user as a numbered/lettered menu
before a job is finalized (see app/agent/tools.py's _build_spec_or_error and
app/agent/prompts.py) -- distinct from param_normalize.py's narrow,
single-pattern typo correctors: this always offers a small set of real
candidates for the user to confirm/pick from, rather than only firing on one
specific known-bad input shape.

Both candidate pools are pyscf's own curated registries (basis-set/
functional naming is a shared, largely program-agnostic convention, not
pyscf-specific), and every candidate is independently re-verified against
pyscf's own parser before being offered -- same "don't offer a candidate
that doesn't actually validate" discipline param_normalize.py already
established, so a suggested option is never a live guess the human then
discovers is bogus.
"""
from __future__ import annotations

import difflib
from functools import lru_cache

# pyscf.gto.basis.ALIAS is keyed by a normalized (lowercase, no punctuation)
# form and doesn't cover Pople-family names at all (those are parsed
# parametrically, not looked up in a static table) -- including exactly the
# "6-31gd" family of typo this feature exists to help catch (see
# param_normalize.py's own module docstring for that bug's history), so a
# small curated list of common Pople names is unioned in alongside the
# ALIAS-derived cc-pVXZ/aug-cc-pVXZ/def2/... names.
_COMMON_POPLE_BASES = (
    "sto-3g", "3-21g", "6-31g", "6-31g*", "6-31g**", "6-31+g*", "6-31+g**", "6-31++g**",
    "6-311g", "6-311g*", "6-311g**", "6-311+g*", "6-311+g**", "6-311++g**",
)


@lru_cache(maxsize=1)
def _basis_name_pool() -> tuple[str, ...]:
    from pyscf.gto import basis as pyscf_basis

    names = set(_COMMON_POPLE_BASES)
    for v in pyscf_basis.ALIAS.values():
        if isinstance(v, str) and v.endswith(".dat"):
            names.add(v[:-4])
    return tuple(sorted(names))


@lru_cache(maxsize=1)
def _functional_name_pool() -> tuple[str, ...]:
    from pyscf.dft import libxc

    return tuple(sorted(libxc.XC_CODES.keys()))


def suggest_basis_options(basis: str | None, n: int = 4) -> list[str]:
    """Up to n basis-set names from pyscf's own registry that most closely
    match `basis`, each independently re-verified via
    param_normalize._pyscf_basis_is_valid before being returned."""
    if not basis:
        return []
    from app.chemistry.jobs.param_normalize import _pyscf_basis_is_valid

    pool = _basis_name_pool()
    matches = difflib.get_close_matches(basis.strip().lower(), pool, n=n, cutoff=0.5)
    return [m for m in matches if _pyscf_basis_is_valid(m)]


def suggest_functional_options(functional: str | None, n: int = 4) -> list[str]:
    """Up to n DFT functional names from pyscf's libxc registry that most
    closely match `functional`."""
    if not functional:
        return []
    from pyscf.dft import libxc

    pool = _functional_name_pool()
    matches = difflib.get_close_matches(functional.strip().lower(), [p.lower() for p in pool], n=n, cutoff=0.5)
    # difflib matched on the lowercased pool; map each match back to its
    # real (pyscf-preferred) casing for display/use.
    lower_to_real = {p.lower(): p for p in pool}
    out = []
    for m in matches:
        real = lower_to_real[m]
        try:
            libxc.parse_xc(real)
        except Exception:
            continue
        out.append(real)
    return out
