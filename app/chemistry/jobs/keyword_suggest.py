"""Mechanical "closest-matching exact syntax keyword" suggestions for basis
sets and DFT functionals, surfaced to the user as a numbered/lettered menu
before a job is finalized (see app/agent/tools.py's _build_spec_or_error and
app/agent/prompts.py) -- distinct from param_normalize.py's narrow,
single-pattern typo correctors: this always offers a small set of real
candidates for the user to confirm/pick from, rather than only firing on one
specific known-bad input shape.

Engine-aware: pyscf's BASIS pool is pyscf's own curated registry
(pyscf.gto.basis.ALIAS), each candidate independently re-verified against
pyscf's own parser before being offered -- "don't offer a candidate that
doesn't actually validate," the same discipline param_normalize.py
established. Functionals no longer live here at all: parse-verification
turned out to be too weak a test for them, since a libxc component name
parses AND computes while being only half a functional, so that pool and
its oracle moved to app/chemistry/jobs/functional.py and this module
delegates. BAGEL has no equivalent
"ask the engine" validity oracle, so its pool is built by directly
parsing its own scraped manual text (data/scraped/bagel/)
rather than routing through this app's Chroma/embeddings KB pipeline --
confirmed during design that semantic similarity search is the wrong tool
here: there's no per-engine metadata on KB chunks to filter by, and ORCA's
basis/functional tables are large enough to fragment across dozens of
chunks, so a top-k search would only ever retrieve a partial name list.
Pool membership itself is the validity oracle for these two engines (the
pool was built from the real manual, so nothing further to re-verify).

All three pool builders below are best-effort: a missing/renamed scraped
file returns an empty pool rather than raising, matching
app/agent/tools.py's _kb_context_for_job's existing "a KB miss shouldn't
block job preparation" posture.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache

from app.config import SCRAPED_DIR

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


# --- BAGEL: data/scraped/bagel/molecule__molecule.html.txt has a clean,
# header-delimited, one-name-per-line list for both the orbital and
# density-fitting basis-set sections -- confirmed by direct inspection, no
# table-row parsing needed the way ORCA requires below. BAGEL has no DFT
# support at all (confirmed zero "dft"/"b3lyp" mentions anywhere in its
# scraped manual), so there is no BAGEL functional pool.
_BAGEL_NOISE_TOKENS = {"basis", "df_basis"}
_LOWER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _bagel_names_in(lines: list[str], start: int, end: int) -> tuple[str, ...]:
    return tuple(sorted({
        l for l in lines[start:end]
        if _LOWER_NAME_RE.match(l) and l not in _BAGEL_NOISE_TOKENS
    }))


@lru_cache(maxsize=1)
def _bagel_basis_sections() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Both BAGEL name lists in one pass, chaining the three boundary
    lookups in known document order -- required because both
    "Density fitting basis sets" and "Effective core potential (ECP) basis
    sets" each appear TWICE in the raw scraped text (once as a
    cross-reference mention earlier in the page, once as the real section
    header) -- confirmed live that searching for either header independently
    from the start of the file finds the wrong (earlier, cross-reference)
    occurrence, which swept a large stretch of unrelated keyword
    documentation into the df-basis pool. Chaining each lookup to start
    just after the previous one resolves to the real headers in sequence."""
    try:
        text = (SCRAPED_DIR / "bagel" / "molecule__molecule.html.txt").read_text("utf-8")
    except OSError:
        return (), ()
    lines = [l.strip() for l in text.splitlines()]
    try:
        i1 = lines.index("Orbital basis sets")
        i2 = lines.index("Density fitting basis sets", i1 + 1)
        i3 = lines.index("Examples", i2 + 1)  # the worked-JSON-example subheading right after the df list
    except ValueError:
        return (), ()
    return _bagel_names_in(lines, i1 + 1, i2), _bagel_names_in(lines, i2 + 1, i3)


@lru_cache(maxsize=1)
def _bagel_basis_name_pool() -> tuple[str, ...]:
    return _bagel_basis_sections()[0]


@lru_cache(maxsize=1)
def _bagel_df_basis_name_pool() -> tuple[str, ...]:
    return _bagel_basis_sections()[1]


# --- ORCA: basis-set names live in a flattened HTML table
# (contents__essentialelements__basisset.html.txt) -- each row's basis name
# is always immediately followed by an element-range line (e.g. "H–Kr",
# "H–Cs, Ga–Kr"), which is the one structurally reliable anchor (the table
# has an optional trailing "Comment" column, so row length isn't fixed).
# Functional keywords live in a similarly flattened table
# (contents__modelchemistries__DensityFunctionalTheory.html.txt) as
# distinct all-uppercase(+digit/hyphen) tokens (the "Keyword(s)" column,
# e.g. "B3LYP", "VWN5"), naturally excluding mixed-case display names and
# citation-bracket digits. Both regexes were verified against real excerpts
# of the actual scraped files, not guessed -- residual noise is possible
# (confirmed live: a handful of ECP-table core-electron-count numbers and
# fragments like "28,MDF" slip through the basis-name scan since they sit
# directly before an element-range-shaped line the same way a real basis
# name does) -- filtered where cheap to do so (pure-numeric tokens), but
# not chased exhaustively; a stray non-basis candidate here just never gets
# picked by a real fuzzy match against real user input.
_ORCA_ELEM_RANGE_RE = re.compile(r"^[A-Z][a-z]?[–-][A-Z][a-z]?(,\s*[A-Z][a-z]?[–-][A-Z][a-z]?)*$")
_ORCA_BASIS_TABLE_NOISE = {"basis set", "elem.", "ecp", "comment"}
_ORCA_FUNCTIONAL_KEYWORD_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-_]{1,}$")


@lru_cache(maxsize=1)
def _orca_basis_name_pool() -> tuple[str, ...]:
    try:
        text = (SCRAPED_DIR / "orca" / "contents__essentialelements__basisset.html.txt").read_text("utf-8")
    except OSError:
        return ()
    lines = [l.strip() for l in text.splitlines()]
    names = set()
    for i in range(1, len(lines)):
        prev, cur = lines[i - 1], lines[i]
        if (
            _ORCA_ELEM_RANGE_RE.match(cur)
            and prev
            and not prev.isdigit()
            and prev.lower() not in _ORCA_BASIS_TABLE_NOISE
            and not _ORCA_ELEM_RANGE_RE.match(prev)
        ):
            names.add(prev)
    return tuple(sorted(names))


# Still here, but no longer a pool anyone offers from: this is now the
# CANDIDATE list that scripts/verify_orca_functionals.py runs through ORCA
# itself, and the verified survivors are what the app uses. The regex is
# deliberately generous for that reason -- a false positive costs one
# 0.2s probe and is then dropped, where a false negative would silently
# lose a real functional.
@lru_cache(maxsize=1)
def _orca_functional_name_pool() -> tuple[str, ...]:
    try:
        text = (SCRAPED_DIR / "orca" / "contents__modelchemistries__DensityFunctionalTheory.html.txt").read_text(
            "utf-8"
        )
    except OSError:
        return ()
    lines = [l.strip() for l in text.splitlines()]
    return tuple(sorted({
        l for l in lines
        if _ORCA_FUNCTIONAL_KEYWORD_RE.match(l) and not l.isdigit()
    }))


_BASIS_POOLS = {"pyscf": _basis_name_pool, "orca": _orca_basis_name_pool, "bagel": _bagel_basis_name_pool}
_DF_BASIS_POOLS = {"bagel": _bagel_df_basis_name_pool}


def suggest_basis_options(basis: str | None, engine: str = "pyscf", n: int = 4) -> list[str]:
    """Up to n basis-set names from `engine`'s own real name registry that
    most closely match `basis`. pyscf candidates are independently
    re-verified via param_normalize._pyscf_basis_is_valid before being
    returned (pyscf has a real "ask the engine" oracle); orca/bagel have no
    such oracle, so pool membership -- built from each engine's own manual
    -- is the validity check there."""
    if not basis:
        return []
    from app.chemistry.jobs.bse_basis import is_bse_ref

    if is_bse_ref(basis):
        return []  # already an exact, resolved choice -- nothing to fuzzy-suggest

    pool_fn = _BASIS_POOLS.get(engine, _basis_name_pool)
    pool = pool_fn()
    if not pool:
        return []
    lower_to_real = {p.lower(): p for p in pool}
    matches = difflib.get_close_matches(basis.strip().lower(), list(lower_to_real), n=n, cutoff=0.5)
    candidates = [lower_to_real[m] for m in matches]
    if engine == "pyscf":
        from app.chemistry.jobs.param_normalize import _pyscf_basis_is_valid

        return [c for c in candidates if _pyscf_basis_is_valid(c)]
    return candidates


def suggest_df_basis_options(df_basis: str | None, engine: str = "bagel", n: int = 4) -> list[str]:
    """Same as suggest_basis_options but for BAGEL's separate df_basis
    (density-fitting) name space -- only BAGEL mandates one, so this is
    bagel-only. A mistyped explicit df_basis gets the same fuzzy-menu
    treatment as basis/functional rather than silently falling through to
    bse_basis.resolve_bagel_df_basis's own auto-matching."""
    if not df_basis:
        return []
    from app.chemistry.jobs.bse_basis import is_bse_ref

    if is_bse_ref(df_basis):
        return []
    pool_fn = _DF_BASIS_POOLS.get(engine)
    if pool_fn is None:
        return []
    pool = pool_fn()
    if not pool:
        return []
    lower_to_real = {p.lower(): p for p in pool}
    matches = difflib.get_close_matches(df_basis.strip().lower(), list(lower_to_real), n=n, cutoff=0.5)
    return [lower_to_real[m] for m in matches]


def suggest_functional_options(functional: str | None, engine: str = "pyscf", n: int = 4) -> list[str]:
    """Up to n DFT functional names to offer, all of which `engine` will
    actually run as a complete functional.

    Delegates to `app.chemistry.jobs.functional`, which is the single
    authority on that question -- so the menu and the resolver that
    rewrites the draft cannot disagree about what is valid.

    This used to fuzzy-match over raw `libxc.XC_CODES`, which is how a
    request for `r2scan` came back offering `MGGA_X_R2SCAN`: r2SCAN's
    exchange half, a real libxc code that parses, computes, and converges
    0.32 Eh from the right answer without a warning. Component-only codes
    are no longer in the pool at all.

    Returns [] when the resolver already settled the name, because there is
    nothing left to choose -- a menu exists to resolve a genuine ambiguity,
    and offering alternatives to a name the engine accepts second-guesses a
    choice the user made.
    """
    if not functional:
        return []
    from app.chemistry.jobs import functional as functional_lookup

    result = functional_lookup.resolve_functional(functional, engine)
    if result.status == functional_lookup.AMBIGUOUS:
        return list(result.options)[:n]
    return []
