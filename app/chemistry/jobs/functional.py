"""One answer to "is this a DFT functional this engine will actually run,
and what is it called here?"

Every other parameter in a job draft is mechanically repaired before it
reaches an engine -- `param_normalize.normalize_method` and
`normalize_basis` do exactly that, and both validate their own rewrites.
The functional never was, and the only stage that looked at it was
`keyword_suggest.suggest_functional_options`, a `difflib` pass over a raw
name pool that produced a menu and never wrote anything back.

That is survivable when the engine complains. It is not survivable when
it does not, and PySCF does not. libxc's namespace mixes complete
functionals with the halves they are built from -- 981 codes, of which
363 are exchange-only, 224 correlation-only and 77 kinetic-energy -- and
all of them parse and compute. Measured on water/STO-3G during the work
that produced this module: a user asking for `r2scan` was offered
`MGGA_X_R2SCAN`, r2SCAN's exchange half with no correlation functional at
all, which converged silently at -74.966394 Eh against the real
functional's -75.286778. Asking for `m062x` offered the correlation half,
9 Eh out. Nothing warned, so the troubleshoot flow never saw it.

Three questions therefore have to be asked separately, and in this order:

    1. Will this name RUN?  `pyscf.scf.dispersion.parse_dft` first, because
       it both rejects the hard-coded blacklist (wb97x-d, wb97x-d3, ...)
       and resolves composites like wb97x-3c that `parse_xc` refuses
       outright. It returns the real (xc, nlc, disp) triple.
    2. Is the DISPERSION version real?  parse_dft happily returns
       disp="d3" for `b3lyp-d3`, and "d3" is not in its own DISP_VERSIONS
       list -- the failure surfaces later as `ValueError: Unknown
       dispersion version d3` from the SCF itself. Found by running it, and
       the reason this check exists at all: without it the resolver would
       have offered `b3lyp-d3` as valid.
    3. Is it a COMPLETE functional?  Decompose the resolved xc into its
       libxc components and check they cover both exchange and
       correlation.

ORCA needs neither, because it cannot make this mistake: its component
keywords (X_BECKE, C_P86, X_TPSS) are values for the Exchange/Correlation
keywords inside a `%method` block, a different namespace from the simple
input line, and `! X_TPSS` is an UNRECOGNIZED KEYWORD. Its pool is a list
verified by running ORCA itself -- see `data/verified/orca_functionals.txt`
and `scripts/verify_orca_functionals.py`.

BAGEL never reaches here. It has no DFT at all (zero mentions across 48
scraped manual pages, no libxc symbols in the 1.2.2 binary, no bagel+dft
row in the capability registry), so `route_engine` refuses a BAGEL DFT
draft one layer earlier, naming pyscf/orca as the alternatives.

See docs/FUNCTIONAL_RESOLVER_PLAN.md for the full rationale and the
measurements behind each rule.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache
from typing import NamedTuple, Optional

from app.config import DATA_DIR

# --- completeness verdicts -------------------------------------------------

COMPLETE = "complete"
EXCHANGE_ONLY = "exchange_only"
CORRELATION_ONLY = "correlation_only"
KINETIC = "kinetic"
UNPARSEABLE = "unparseable"
BLACKLISTED = "blacklisted"
BAD_DISPERSION = "bad_dispersion"


def _dispersion_is_real(disp: str) -> bool:
    """Is this one of the damping schemes simple-dftd3/dftd4 implements?

    `parse_dft` returns whatever suffix it split off without checking, and
    the whitelisted composites return a prefixed form ("d4:wb97x-3c"), so
    the leading token before ":" is what has to be in DISP_VERSIONS.
    """
    from pyscf.scf.dispersion import DISP_VERSIONS

    return str(disp).split(":", 1)[0] in DISP_VERSIONS


@lru_cache(maxsize=1)
def _id_to_name() -> dict[int, str]:
    """libxc functional id -> its canonical name.

    Inverts `libxc.XC_CODES`, preferring the FAMILY_KIND_NAME form over a
    bare alias when both map to one id: the prefixed name is the one that
    carries the X/C/XC/K token this module reads.

    Two traps, both confirmed live rather than guessed. 942 of the 981
    values are `numpy.int32` rather than `int`, so an `isinstance(v, int)`
    filter silently drops almost the entire table -- which is exactly the
    bug that made an earlier draft of this function classify everything as
    UNKNOWN. And 20 values are not ids at all but recipe strings, e.g.
    REVPBE0 is `".25*HF + .75*PBE_R, PBE"`; they have no id to invert and
    are skipped here, but they ARE real functionals and the pool builder
    below has to include them as candidates.
    """
    from pyscf.dft import libxc

    out: dict[int, str] = {}
    for name, value in libxc.XC_CODES.items():
        if isinstance(value, str):
            continue
        key = int(value)
        previous = out.get(key)
        if previous is None or ("_" in name and "_" not in previous):
            out[key] = name
    return out


@lru_cache(maxsize=1)
def _blacklisted_keys() -> frozenset[str]:
    """Every match key PySCF refuses to run, however it is spelled."""
    from pyscf.scf.dispersion import _black_list

    return frozenset(match_key(name) for name in _black_list)


def _kind_token(libxc_name: str) -> str:
    """X, C, XC, K or BARE, read off a libxc name's own FAMILY_KIND_NAME
    structure. Order matters: `_XC_` has to be tested before `_X_` or a
    compound reads as exchange-only."""
    for token in ("_XC_", "_X_", "_C_", "_K_"):
        if token in libxc_name:
            return token.strip("_")
    # A bare name that still ends in a kind suffix -- LDA_X is the real
    # case -- is a component too, and would otherwise read as BARE.
    for suffix in ("_XC", "_X", "_C", "_K"):
        if libxc_name.endswith(suffix):
            return suffix.strip("_")
    return "BARE"


def pyscf_verdict(name: str) -> tuple[str, Optional[str], tuple[str, ...]]:
    """(verdict, resolved_xc, component names) for one candidate name.

    `resolved_xc` is what PySCF would actually compute with, which is not
    always what was passed in -- `wb97x-d3bj` resolves to `wb97x-v` plus a
    d3bj correction, and `wb97x-3c` to `wb97x-v` plus d4.
    """
    from pyscf.dft import libxc
    from pyscf.scf.dispersion import parse_dft

    # 0. Is any spelling of this functional blacklisted? PySCF's own list
    #    holds only the separated spellings -- "wb97x-d" and "wb97x_d" are
    #    there, "wb97xd" is not -- so the unseparated form sails past
    #    parse_dft, runs, and silently computes wB97X-D with no dispersion
    #    term at all. That is the same silent-wrong-answer this module
    #    exists to stop, arriving through a spelling loophole, so the
    #    blacklist is matched on the key rather than the literal string.
    if match_key(name) in _blacklisted_keys():
        return BLACKLISTED, None, ()

    # 1. Will it run? parse_dft first: it rejects the blacklist AND
    #    resolves composites that parse_xc alone refuses.
    try:
        resolved_xc, _nlc, disp = parse_dft(name)
    except NotImplementedError:
        return BLACKLISTED, None, ()
    except Exception:
        return UNPARSEABLE, None, ()

    # 2. Is the dispersion version one simple-dftd3/dftd4 actually knows?
    #    parse_dft does not check its own output here: `b3lyp-d3` comes back
    #    as disp="d3", which is absent from DISP_VERSIONS and blows up in
    #    the SCF. A bare "-d3" is genuinely ambiguous anyway -- D3(BJ) and
    #    D3(zero) give different energies (-75.31295765 vs -75.31239164 on
    #    water/STO-3G) -- so this is a name the user has to disambiguate,
    #    not one to guess at.
    if disp is not None and not _dispersion_is_real(disp):
        return BAD_DISPERSION, resolved_xc, ()

    # 3. Is it complete? Decompose whatever parse_dft resolved to.
    try:
        _hyb, fn_facs = libxc.parse_xc(resolved_xc)
    except Exception:
        return UNPARSEABLE, resolved_xc, ()

    id_to_name = _id_to_name()
    components = tuple(id_to_name.get(int(i), f"id{int(i)}") for i, _ in fn_facs)
    if not components:
        return UNPARSEABLE, resolved_xc, ()

    kinds = {_kind_token(c) for c in components}
    if "K" in kinds:
        return KINETIC, resolved_xc, components
    has_exchange = "X" in kinds or "XC" in kinds
    has_correlation = "C" in kinds or "XC" in kinds
    if has_exchange and has_correlation:
        return COMPLETE, resolved_xc, components
    if has_exchange:
        return EXCHANGE_ONLY, resolved_xc, components
    if has_correlation:
        return CORRELATION_ONLY, resolved_xc, components
    return UNPARSEABLE, resolved_xc, components


def pyscf_accepts(name: str) -> bool:
    """The single gate. A name is offerable only if it both runs and is a
    whole functional."""
    return pyscf_verdict(name)[0] == COMPLETE


# --- the offerable-name pool ----------------------------------------------

# PySCF resolves a bare name it does not find by trying FAMILY_X_NAME plus
# FAMILY_C_NAME, which is how `r2scan` works despite R2SCAN not being a key
# in XC_CODES at all. So the human-facing names are the TRAILING parts of
# the libxc codes, not the codes themselves -- and a trailing name is a
# whole functional when either an _XC_ code carries it, or an _X_ and a _C_
# code both do.
def _trailing(code: str) -> Optional[str]:
    for token in ("_XC_", "_X_", "_C_"):
        if token in code:
            return code.split(token, 1)[1]
    return None


@lru_cache(maxsize=1)
def pyscf_functional_pool() -> tuple[str, ...]:
    """Every name PySCF will run as a complete functional, in the spelling
    a chemist would write it.

    Candidate generation is deliberately generous and the oracle does the
    rejecting -- `pyscf_verdict` is the authority, this just decides what
    to ask it about. Raw FAMILY_KIND_NAME codes are never included: nobody
    types `HYB_GGA_XC_WB97XD`, and offering it is how ωB97X-D's dispersion
    term went missing without anything failing.
    """
    from pyscf.dft import libxc

    exchange, correlation, compound = set(), set(), set()
    # Recipe-valued keys (REVPBE0 = ".25*HF + .75*PBE_R, PBE") are whole
    # functionals by construction and carry no kind token to read, so they
    # go straight in as candidates. Missing them is how an earlier draft of
    # this pool dropped revpbe0 while keeping revpbe.
    bare = {k for k, v in libxc.XC_CODES.items() if isinstance(v, str)}
    for code in [k for k, v in libxc.XC_CODES.items() if not isinstance(v, str)]:
        tail = _trailing(code)
        if tail is None:
            if not any(t in code for t in ("_X_", "_C_", "_XC_", "_K_")):
                bare.add(code)
            continue
        if "_XC_" in code:
            compound.add(tail)
        elif "_X_" in code:
            exchange.add(tail)
        elif "_C_" in code:
            correlation.add(tail)

    candidates = compound | (exchange & correlation) | bare
    candidates |= set(getattr(libxc, "XC_ALIAS", {}) or {})

    accepted: dict[str, str] = {}
    for candidate in candidates:
        # Chemists write hyphens (m06-2x, wb97x-v); libxc codes carry
        # underscores. Offer whichever form PySCF actually takes, preferring
        # the hyphenated one because that is what a person types.
        for form in (candidate.replace("_", "-").lower(), candidate.lower()):
            if not pyscf_accepts(form):
                continue
            # libxc often carries the same functional under two spellings
            # (b3lyp_mcm1 and b3lypmcm1 are both real keys, 94 such pairs).
            # Keep one per match key, preferring the separated spelling --
            # it is the readable one, and a fuzzy menu offering both wastes
            # a slot on a name that is not a different choice.
            key = match_key(form)
            current = accepted.get(key)
            if current is None or (("-" in form or "_" in form) and "-" not in current and "_" not in current):
                accepted[key] = form
            break
    return tuple(sorted(accepted.values()))


_ORCA_POOL_FILE = DATA_DIR / "verified" / "orca_functionals.txt"


@lru_cache(maxsize=1)
def orca_functional_pool() -> tuple[str, ...]:
    """ORCA's simple-input functional keywords, as verified by running ORCA.

    Not scraped. The previous pool was a regex over all-caps tokens in the
    manual's DFT chapter, which admitted table fragments -- X_TPSS,
    B97X-D3 and WHPBE0 are all confirmed rejected by ORCA itself -- and
    which ranked M06-2X above M062X even though ORCA accepts only the
    latter. See scripts/verify_orca_functionals.py for how this file is
    regenerated; it needs a licensed ORCA binary, so it is committed as
    data rather than rebuilt on demand.

    A missing file yields an empty pool rather than raising, matching the
    best-effort posture of every other pool builder in this package.
    """
    try:
        text = _ORCA_POOL_FILE.read_text("utf-8")
    except OSError:
        return ()
    names = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return tuple(sorted(set(names)))


# --- normalization ---------------------------------------------------------

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def match_key(name: str) -> str:
    """The form two spellings of one functional agree on: casefolded, with
    every separator dropped. M06-2X, m062x and M06_2X all key to `m062x`.

    Only ever used for MATCHING. What comes back to the user is always the
    engine's own real spelling, which differs between engines -- ORCA takes
    M062X and rejects M06-2X, verified by running both.
    """
    return _NON_ALNUM.sub("", (name or "").strip().lower())


# --- dispersion ------------------------------------------------------------

# What each engine will accept as a damping scheme, and how it wants it
# written. PySCF takes one token (`b3lyp-d3bj`); ORCA takes two
# (`B3LYP D3BJ`) and rejects the hyphenated form outright. Both verified
# by running them.
#
# Bare "d3" is the interesting one. ORCA accepts `B3LYP D3` and has meant
# BJ damping by it for years, so it resolves cleanly there. PySCF's
# parse_dft splits it off happily and then the SCF dies with "Unknown
# dispersion version d3" -- and the two dampings genuinely differ
# (-75.31295765 for d3bj against -75.31239164 for d3zero on water/STO-3G),
# so on PySCF this is a question for the user rather than a default to
# pick for them.
_PYSCF_DISPERSIONS = ("d3bj", "d3zero", "d3bjm", "d3zerom", "d3op", "d4")
_ORCA_DISPERSIONS = ("d3", "d3bj", "d3zero", "d4")
_AMBIGUOUS_ON_PYSCF = {"d3": ("d3bj", "d3zero")}

_DISP_SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)[-_ ]?(?P<disp>d3bjm|d3zerom|d3zero|d3bj|d3op|d4|d3)$", re.IGNORECASE
)


def split_dispersion(name: str) -> tuple[str, Optional[str]]:
    """(base functional, damping scheme) for a name written as one token.

    Only a split -- it makes no claim that either half is valid. The
    caller checks the base against the engine's pool and the damping
    against that engine's list, because a name can look like a split and
    not be one: ωB97X-D3 and B97-D3 are single published functionals, not
    a base plus a correction, which is why every caller here tries an
    exact pool hit before reaching for this.
    """
    match = _DISP_SUFFIX_RE.match((name or "").strip())
    if not match:
        return (name or "").strip(), None
    return match.group("base"), match.group("disp").lower()


# --- the cross-engine table ------------------------------------------------

# Only what the mechanical layers above cannot reach. Every row was
# verified on this host; if a row can be derived from the pools, it does
# not belong here.
#
# Keyed on match_key(), so spelling variants of the request all land on
# the same row.
_CURATED: dict[str, dict[str, tuple[Optional[str], str]]] = {
    # (engine -> (resolved name or None, note))
    "wb97xd": {
        "pyscf": ("wb97x-d3bj", "PySCF cannot run wB97X-D: it is blacklisted in pyscf/scf/dispersion.py "
                                "and no install changes that. wB97X-D3BJ is its supported near-equivalent."),
        "orca": ("WB97X-D3", "ORCA writes this functional as WB97X-D3; it has no bare WB97X-D keyword."),
    },
    "wb97xd3": {
        "pyscf": ("wb97x-d3bj", "PySCF cannot run wB97X-D3: it is blacklisted in pyscf/scf/dispersion.py "
                                "and no install changes that. wB97X-D3BJ is its supported near-equivalent."),
    },
    # !SCAN collides with ORCA's relaxed-surface-scan keyword, so the
    # functional is SCANFUNC there. Confirmed by running both.
    "scan": {
        "orca": ("SCANFUNC", "ORCA calls the SCAN functional SCANFUNC -- plain SCAN is its geometry-scan keyword."),
    },
}


# --- resolution ------------------------------------------------------------

EXACT = "exact"
REWRITE = "rewrite"
AMBIGUOUS = "ambiguous"
UNSUPPORTED_HERE = "unsupported_here"
UNKNOWN = "unknown"

_ENGINE_POOLS = {"pyscf": pyscf_functional_pool, "orca": orca_functional_pool}


@lru_cache(maxsize=8)
def _key_index(engine: str) -> dict[str, str]:
    """match_key -> the engine's own spelling."""
    pool_fn = _ENGINE_POOLS.get(engine)
    if pool_fn is None:
        return {}
    return {match_key(name): name for name in pool_fn()}


def _compose(engine: str, base_name: str, disp: str) -> Optional[str]:
    """Write `base + damping` the way this engine wants it, or None if this
    engine will not take that damping."""
    if engine == "pyscf":
        if disp not in _PYSCF_DISPERSIONS:
            return None
        candidate = f"{base_name}-{disp}"
        return candidate if pyscf_accepts(candidate) else None
    if engine == "orca":
        if disp not in _ORCA_DISPERSIONS:
            return None
        return f"{base_name} {disp.upper()}"
    return None


class Resolution(NamedTuple):
    """What the resolver concluded, and what to do about it.

    `status` drives the caller:
      exact            -- use `resolved`, show no menu. A correct choice
                          is never second-guessed.
      rewrite          -- use `resolved`, surface `note` as a param_note so
                          the change is visible on the approval card before
                          anything runs.
      ambiguous        -- ask. `options` are all real, runnable, complete
                          names in this engine's own spelling.
      unsupported_here -- this engine cannot, `other_engine` can.
      unknown          -- nothing close enough to offer honestly.
    """

    status: str
    resolved: Optional[str] = None
    note: Optional[str] = None
    options: tuple[str, ...] = ()
    other_engine: Optional[str] = None


def resolve_functional(functional: Optional[str], engine: str) -> Resolution:
    """Turn what someone typed into what `engine` actually calls it.

    The order below is the whole design. An exact hit wins before anything
    clever runs, because ωB97X-D3 and B97-D are single published
    functionals whose names merely look like a base plus a correction --
    reaching for the dispersion splitter first would take them apart and
    resolve them to something else.
    """
    if not functional or not str(functional).strip():
        return Resolution(UNKNOWN)
    if engine not in _ENGINE_POOLS:
        # BAGEL, or an engine with no DFT. Nothing to resolve, and nothing
        # should have got this far -- route_engine refuses a BAGEL DFT
        # draft an entire layer earlier.
        return Resolution(UNKNOWN)

    raw = str(functional).strip()
    key = match_key(raw)
    index = _key_index(engine)

    # 1. Exact, by match key. Spelling differences are not a choice.
    if key in index:
        real = index[key]
        if real == raw:
            return Resolution(EXACT, real)
        return Resolution(REWRITE, real, f"Wrote the functional as {real}, which is how {engine.upper()} spells it.")

    # 2. The curated cross-engine table.
    row = _CURATED.get(key)
    if row is not None:
        entry = row.get(engine)
        if entry is not None:
            resolved, note = entry
            if resolved is not None:
                return Resolution(REWRITE, resolved, note)
        other = next((e for e in _ENGINE_POOLS if e != engine and e in row), None)
        if other is not None:
            return Resolution(UNSUPPORTED_HERE, None, row[other][1], (), other)

    # 3. A base functional plus a damping scheme.
    base, disp = split_dispersion(raw)
    if disp is not None:
        base_real = index.get(match_key(base))
        if base_real is not None:
            composed = _compose(engine, base_real, disp)
            if composed is not None:
                return Resolution(
                    REWRITE, composed,
                    f"Wrote {raw} as {composed}, which is how {engine.upper()} takes that dispersion correction.",
                )
            # The engine knows the functional but not that damping. On
            # PySCF a bare "-d3" is exactly this, and the two dampings are
            # different chemistry, so offer both rather than choose.
            alternatives = _AMBIGUOUS_ON_PYSCF.get(disp, ())
            options = tuple(
                c for c in (_compose(engine, base_real, d) for d in alternatives) if c is not None
            )
            if options:
                return Resolution(
                    AMBIGUOUS, None,
                    f"{engine.upper()} needs the damping scheme named explicitly -- "
                    f"D3(BJ) and D3(zero) give different energies.",
                    options,
                )

    # 4. Valid on the other engine but not here.
    for other in _ENGINE_POOLS:
        if other == engine:
            continue
        if key in _key_index(other):
            return Resolution(
                UNSUPPORTED_HERE, None,
                f"{other.upper()} has {_key_index(other)[key]}, but {engine.upper()} does not offer it.",
                (), other,
            )

    # 5. Closest real names, for a menu. Matched on the key rather than the
    #    raw string so punctuation differences do not cost similarity.
    close = difflib.get_close_matches(key, list(index), n=4, cutoff=0.6)
    if close:
        return Resolution(AMBIGUOUS, None, None, tuple(index[k] for k in close))
    return Resolution(UNKNOWN)
