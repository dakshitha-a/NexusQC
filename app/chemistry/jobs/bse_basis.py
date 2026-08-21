"""Basis Set Exchange (BSE) integration: resolves the `"bse:<name>"` basis
sentinel (see keyword_suggest.py's suggestion menu / the resolve_basis_from_bse
agent tool in app/agent/tools.py) into whatever native basis representation
each engine's runner needs.

The basis_set_exchange PyPI package is fully offline -- confirmed by
inspecting the installed wheel: ~4000 data files ship inside the package
itself, and get_basis()/get_metadata()/get_all_basis_names() never make a
network call. Every function below is therefore a deterministic, pure
function of (canonical_name, elements), called from the SAME choke point
each engine's ordinary basis handling already goes through
(pyscf_runner.build_mole, bagel_runner._build_input, orca_runner's
_resolve_basis_directive feeding build_input_text) -- so "what's approved is
exactly what runs" holds for a BSE-resolved basis with no special-casing
needed anywhere in app/agent/tools.py.

params["basis"] never carries translated/structured data -- only ever a
plain string, either an ordinary engine-native name or this module's
"bse:<name>" sentinel. All translation happens lazily, inside each engine's
runner, which is why nothing upstream (param normalization, engine
resolution, the interrupt()/resume boundary) needs to change shape to
support this.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from functools import lru_cache

BSE_PREFIX = "bse:"


def is_bse_ref(basis) -> bool:
    """True if `basis` is the "bse:<name>" sentinel this module resolves.
    Guards every non-BSE code path (param_normalize.normalize_basis,
    keyword_suggest.suggest_basis_options) so an already-exact BSE choice is
    never re-typo-corrected or re-fuzzy-suggested against."""
    return isinstance(basis, str) and basis.lower().startswith(BSE_PREFIX)


def bse_name(basis: str) -> str:
    return basis[len(BSE_PREFIX):]


@lru_cache(maxsize=1)
def _all_names() -> tuple[str, ...]:
    import basis_set_exchange as bse

    return tuple(bse.get_all_basis_names())


def resolve_bse_name(query: str) -> str | None:
    """Exact match only (case-insensitive) -- BSE's own get_basis() lookup
    has no fuzzy layer of its own (transform_basis_name() does an exact dict
    lookup), so this is the boundary where this app's own fuzzy layer
    (search_bse_basis_names) hands off to a name BSE will actually accept."""
    lower_to_real = {n.lower(): n for n in _all_names()}
    return lower_to_real.get(query.strip().lower())


def search_bse_basis_names(query: str, n: int = 8) -> list[str]:
    lower_to_real = {p.lower(): p for p in _all_names()}
    matches = difflib.get_close_matches(query.strip().lower(), list(lower_to_real), n=n, cutoff=0.4)
    return [lower_to_real[m] for m in matches]


# --- Phase 1: PySCF -----------------------------------------------------

def pyscf_basis_dict(name: str, elements: list[str]) -> dict:
    """Returns {element_symbol: parsed_shell_list}, directly assignable to
    mol.basis -- verified live: bse.get_basis(..., fmt="nwchem") text feeds
    pyscf.gto.basis.parse() cleanly, and a real gto.Mole() built from the
    resulting per-element dict builds without error."""
    import basis_set_exchange as bse
    from pyscf.gto import basis as pyscf_basis

    out = {}
    for el in sorted(set(elements)):
        nwchem_text = bse.get_basis(name, elements=[el], fmt="nwchem", header=False)
        out[el] = pyscf_basis.parse(nwchem_text)
    return out


# --- Phase 2: BAGEL -------------------------------------------------------

_ANGULAR_LETTERS = "spdfghik"  # BAGEL's own "angular" field, one letter per shell -- confirmed against a real
# basis file from a BAGEL install's own share/ directory, not the manual alone.


def _z_to_symbol(z: int) -> str:
    from pyscf.data import elements

    return elements.ELEMENTS[z]


def bagel_bse_basis_path(name: str, elements: list[str]) -> str:
    """Translates a BSE basis into BAGEL's own per-element shell JSON shape
    and writes it to a deterministic, content-hashed path under
    config.BSE_BAGEL_CACHE_DIR, returning that absolute path -- BAGEL's own
    "basis"/"df_basis" fields accept an explicit filesystem path (confirmed
    directly against the BAGEL manual's "User defined basis sets" section:
    "the explicit path to the basis set file must be specified"), so no
    change is needed to bagel_runner._molecule_block at all.

    Uses basis_set_exchange.manip.uncontract_general(basis, True) followed
    by manip.uncontract_spdf(basis, max_am=0) -- both steps confirmed
    necessary by diffing translator output against real basis files from a
    BAGEL install's own share/ directory:

    - uncontract_general splits a general contraction (one shared primitive
      set, several contraction-coefficient columns -- BSE's/pyscf's own
      native representation, e.g. for cc-pVDZ) into separate single-row-
      "cont" shell entries. This is required because BAGEL's own format
      NEVER uses a multi-row "cont" -- confirmed against a real
      ano-rcc.json (a heavily generally-contracted basis) where every shell
      entry has exactly one "cont" row; a general contraction is instead
      several separate shell entries sharing the same "prim" list. Skipping
      this step produces a structurally-different (though not
      BAGEL-rejected-at-parse-time) shape than BAGEL's own basis files use.
    - uncontract_spdf(..., max_am=0) -- NOT max_am=1, which is what
      basis_set_exchange's own GAMESS-US/ORCA writers use to keep combined
      S+P ("SP"/"L") shells intact for those programs. BAGEL (like ORCA's
      own NewGTO format, confirmed against its manual: "Combined s- and
      p-shells... [are] not supported in the NewGTO format") has no
      combined-shell concept at all, so max_am=0 is required to fully split
      every SP/SPD/... shell down to single angular momentum per shell.

    This is a pure function of (name, elements) -- safe to call repeatedly
    (submit_draft's pre-interrupt() code reruns on every resume) and safe to
    cache by content hash rather than by call site.
    """
    from basis_set_exchange import manip
    import basis_set_exchange as bse
    from app.config import BSE_BAGEL_CACHE_DIR

    els = sorted(set(elements))
    key = hashlib.sha1(f"{name}|{','.join(els)}".encode()).hexdigest()[:16]
    safe_name = name.lower().replace("/", "_sl_").replace("*", "_st_")
    path = BSE_BAGEL_CACHE_DIR / f"{safe_name}-{key}.json"
    if path.exists():
        return str(path)

    raw = bse.get_basis(name, elements=els)
    general_split = manip.uncontract_general(raw, True)
    split = manip.uncontract_spdf(general_split, 0, False)

    translated: dict[str, list[dict]] = {}
    for z_str, el_data in split["elements"].items():
        symbol = _z_to_symbol(int(z_str))
        shells = []
        for shell in el_data.get("electron_shells", []):
            am = shell["angular_momentum"][0]  # single AM per shell, guaranteed by max_am=0 above
            shells.append({
                "angular": _ANGULAR_LETTERS[am],
                "prim": [float(e) for e in shell["exponents"]],
                "cont": [[float(c) for c in row] for row in shell["coefficients"]],
            })
        translated[symbol] = shells

    path.write_text(json.dumps(translated, indent=2))
    return str(path)


def resolve_bagel_df_basis(orbital_basis: str, explicit_df_basis: str | None, elements: list[str]) -> tuple[str, bool]:
    """Resolves BAGEL's mandatory df_basis field -- BAGEL has no "no
    density-fitting" mode, every job carries one -- so this must always
    produce a genuinely matched fitting basis, not a silent generic guess,
    whether the orbital basis is one of BAGEL's included ones or imported
    from BSE. Returns (df_basis_value, exact_match).

    1. An explicit df_basis (including its own possible "bse:" prefix) is
       always honored -- a user/agent who named one is trusted.
    2. Otherwise, bagel_runner._DF_BASIS_MAP's small hardcoded family list
       is tried first (fast, no BSE dependency for the families it covers)
       -- checked against the orbital basis's NAME, with any "bse:" prefix
       stripped first: a BSE-imported basis that happens to be one of
       BAGEL's already-covered families (e.g. "bse:cc-pVDZ") must still hit
       this fast path and get BAGEL's own curated "cc-pvdz-jkfit", not fall
       through to step 3 -- confirmed this matters live: without the strip,
       every BSE-imported cc-pVDZ/def2-svp/etc. request missed this map
       entirely even though it's the exact family the map already covers.
    3. Otherwise, resolve the orbital basis to a BSE-known canonical name
       (already exact if it was itself "bse:"-imported) and ask BSE's own
       basis_set_exchange.lookup_basis_by_role(name, role) for a real
       matching fitting basis, trying "jkfit" first then "rifit" as a
       fallback role. Confirmed empirically that BSE's own role metadata is
       family-dependent: the def2/Ahlrichs family has a real "jkfit" role
       registered, but the cc-pVXZ family only has "rifit" (no "jkfit" at
       all) -- BAGEL's own hardcoded cc-pVXZ entries in _DF_BASIS_MAP are
       already the fast path for that specific family (step 2), so this
       step's "rifit" fallback only matters for basis families neither
       source curates (e.g. aug-cc-pVQZ, ANO-RCC). A "rifit" match is a
       real, BSE-verified auxiliary basis but built for post-HF correlation
       fitting rather than BAGEL's JK/Fock-fitting use -- reported as
       exact_match=True regardless (it's a genuine match, not a guess), but
       future work could distinguish the two in the surfaced note.
    4. Only if every step above fails does this fall back to
       bagel_runner._DF_BASIS_MAP's existing generic default -- now a true
       last resort rather than the default outcome for most BSE-imported
       orbital bases.
    """
    from app.chemistry.jobs.bagel_runner import _DF_BASIS_MAP, _DEFAULT_DF_BASIS

    if explicit_df_basis:
        if is_bse_ref(explicit_df_basis):
            canonical = resolve_bse_name(bse_name(explicit_df_basis))
            if canonical is None:
                # Falls through to the generic default below rather than
                # raising -- callers (bagel_runner) surface exact_match=False
                # to the approval card same as any other unrecognized name.
                return _DEFAULT_DF_BASIS, False
            return bagel_bse_basis_path(canonical, elements), True
        return explicit_df_basis, True

    orbital_name = bse_name(orbital_basis) if is_bse_ref(orbital_basis) else orbital_basis
    key = orbital_name.strip().lower()
    if key in _DF_BASIS_MAP:
        return _DF_BASIS_MAP[key], True

    canonical = orbital_name if is_bse_ref(orbital_basis) else resolve_bse_name(orbital_basis)
    if canonical is not None:
        import basis_set_exchange as bse

        for role in ("jkfit", "rifit"):
            try:
                fit_name = bse.lookup_basis_by_role(canonical, role)
            except Exception:
                fit_name = None
            # Despite its docstring claiming a plain str return,
            # lookup_basis_by_role was observed live to return a list --
            # confirmed harmless to just take the first entry.
            if isinstance(fit_name, list):
                fit_name = fit_name[0] if fit_name else None
            if fit_name:
                return bagel_bse_basis_path(fit_name, elements), True

    return _DEFAULT_DF_BASIS, False


# --- Phase 3: ORCA ---------------------------------------------------------

def orca_basis_block(name: str, elements: list[str]) -> str:
    """basis_set_exchange's fmt='orca' writer is a naming trap: reading
    writers/orca.py shows write_orca() reuses GAMESS-US's $DATA/$END
    wrapper for the electronic basis (write_gamess_us_common) -- NOT ORCA's
    real %basis NewGTO syntax; only its ECP writer is genuinely ORCA-native.
    This fetches fmt="gamess_us" per element instead and rewraps it: the
    per-shell numeric rows (AM letter + nprim header, then idx/exponent/
    coefficient lines) are verified byte-for-byte identical in shape to
    ORCA's own documented NewGTO block format (confirmed against the real
    ORCA manual's own worked NewGTO example) -- only the $DATA/blank/
    element-name header and trailing blank+$END footer need stripping.

    Verified live end-to-end: the block this produces was run through a
    real ORCA 6.1.1 HF/water job with the basis keyword omitted from the
    '!' line entirely, and it completed normally (FINAL SINGLE POINT
    ENERGY, ORCA TERMINATED NORMALLY) with the expected HF/cc-pVDZ energy.
    """
    import basis_set_exchange as bse

    lines = ["%basis"]
    for el in sorted(set(elements)):
        text = bse.get_basis(name, elements=[el], fmt="gamess_us", header=False)
        raw_lines = text.splitlines()
        # First 3 lines are always "$DATA", a blank line, then the element
        # name (e.g. "OXYGEN") -- confirmed against real generated output;
        # this app doesn't need that name since it already knows the real
        # symbol from the per-element `el` this call was made with.
        body = raw_lines[3:]
        while body and body[-1].strip() in ("", "$END"):
            body.pop()
        lines.append(f"  NewGTO {el}")
        lines.extend(f"  {l}" for l in body)
        lines.append("  end")
    lines.append("end")
    return "\n".join(lines)
