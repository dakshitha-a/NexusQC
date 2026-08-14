"""Best-effort, mechanical correction for two parameters the LLM/user get
wrong in predictable ways: the QC method name ("hf" vs "rhf"/"uhf"/"rohf"
or a plain typo like "rfh") and Pople-style basis-set polarization/diffuse
suffixes glued on without punctuation ("6-31gd" instead of "6-31g(d)" or
"6-31g*"). The basis case is a real, previously-hit bug in this app -- see
CLAUDE.md's _kb_context_for_job note, where "6-31gd" reached PySCF
unparsed and surfaced as a bare KeyError instead of being caught earlier.
That was only ever fixed by the LLM eventually noticing the engine's own
runtime error and correcting itself within MAX_AUTO_RETRIES tries; this
module closes the gap mechanically, before a job is ever submitted, in
line with this codebase's general preference for structural fixes over
prompt-dependent ones (see CLAUDE.md's NotRequired/oscillator-strength-
routing notes for the established precedent).

Both normalizers are deliberately conservative: a value is only ever
rewritten when (1) it does NOT already validate as given, and (2) the
rewrite itself is independently confirmed valid before being used --
basis names against PySCF's own basis-name parser, the one authoritative,
offline-checkable oracle available here. This runs before default_engine()
resolves which engine the job will actually use, so the same rewrite is
applied regardless of destination engine, but it is only actually VERIFIED
against PySCF's parser -- Pople-style parenthesized polarization syntax
like '(d,p)' is the standard literature convention and ORCA is known to
accept it too, but this has not been separately confirmed against ORCA's
own parser, and BAGEL's basis files (checked directly under its install's
share/ directory, e.g. 6-31g.json) don't appear to name polarization
variants this way at all -- for BAGEL specifically this rewrite is best
understood as functionally neutral (a basis string BAGEL would reject
stays rejected either way) rather than a confirmed fix. Method names are
checked against a small explicit alias table plus a tight fuzzy-match
fallback. Anything that doesn't match -- including a genuinely
different/unsupported value like "mp2" or "ccsd"
in the method field -- is left completely untouched and falls through to
the existing "missing/unsupported parameter" error path unchanged. This
is spelling/formatting correction, never a guess at different chemistry
than what was actually asked for.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache
from typing import Optional

# The only two values any runner in this app's "method" parameter ever
# branches on (see registry.py's PARAM_HELP) -- restricted vs. unrestricted
# reference is chosen automatically from the molecule's spin, not exposed
# as a separate choice, so RHF/UHF/ROHF (and common typos/spacing/hyphen
# variants of them, collapsed by the alnum-only key below) all mean "hf"
# here. 'rfh' is kept explicit since it's the exact transposition typo
# that motivated this module, not left to the fuzzy fallback alone.
_METHOD_ALIASES = {
    "hf": "hf", "rhf": "hf", "uhf": "hf", "rohf": "hf", "rfh": "hf",
    "hartreefock": "hf", "restrictedhartreefock": "hf", "unrestrictedhartreefock": "hf",
    "dft": "dft", "ks": "dft", "kohnsham": "dft", "rks": "dft", "uks": "dft", "roks": "dft",
}


def normalize_method(method: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Returns (normalized_method, note); note is None when nothing
    changed, including when `method` doesn't resemble anything recognized
    (left untouched for the existing "Unsupported method" error to
    handle)."""
    if not method:
        return method, None
    key = re.sub(r"[^a-z]", "", method.lower())
    canonical = _METHOD_ALIASES.get(key)
    if canonical is None:
        # Tight cutoff, single best match only -- catches an unlisted typo
        # (e.g. a stray/dropped letter) without ever coercing a genuinely
        # different method name (mp2, ccsd, casscf, ...) into hf/dft.
        close = difflib.get_close_matches(key, _METHOD_ALIASES.keys(), n=1, cutoff=0.75)
        canonical = _METHOD_ALIASES[close[0]] if close else None
    if canonical is None or canonical == method.lower():
        return method, None
    return canonical, (
        f"Interpreted method '{method}' as '{canonical}' (restricted/unrestricted reference is chosen "
        f"automatically from the molecule's spin, not from this parameter)."
    )


@lru_cache(maxsize=512)
def _pyscf_basis_is_valid(name: str) -> bool:
    # Deferred import -- pyscf is a heavy dependency this module (imported
    # from tools.py, which runs in the main server process) should not pay
    # for at import time regardless of which engine a job actually targets,
    # matching the lazy-import convention already used elsewhere for pyscf
    # (see preview.py's build_input_preview).
    from pyscf.gto import basis as pyscf_basis
    try:
        pyscf_basis.load(name, "H")
        return True
    except Exception:
        return False


# A Pople-family basis name ("6-31G", "6-311+G", "3-21G", ...) with a
# polarization/diffuse suffix glued on directly instead of parenthesized
# ("6-31Gd" instead of "6-31G(d)"). The suffix is restricted to digits and
# the angular-momentum letters that actually appear in real polarization
# shorthand (d/f/p/g and counts, e.g. "2d", "3df", "dp") -- NOT bare
# `[a-zA-Z0-9]+`, since PySCF's parser silently accepts (and drops) an
# unrecognized parenthesized suffix rather than raising, e.g.
# "6-31G(zzz)" loads "successfully" as plain unpolarized 6-31G. Without
# this restriction the "fix" would validate but silently discard whatever
# nonsense suffix the user typed instead of actually catching a typo.
_POPLE_GLUED_SUFFIX = re.compile(r"^(?P<base>\d+-\d{2,3}\+{0,2}g)(?P<suffix>[0-9dfgpDFGP]+)$", re.IGNORECASE)


def normalize_basis(basis: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Returns (normalized_basis, note); note is None when nothing
    changed, including when `basis` is already valid as given or doesn't
    match the one specific typo pattern this handles."""
    if not basis:
        return basis, None
    if _pyscf_basis_is_valid(basis):
        return basis, None
    m = _POPLE_GLUED_SUFFIX.match(basis.strip())
    if not m:
        return basis, None
    candidate = f"{m.group('base')}({m.group('suffix')})"
    if not _pyscf_basis_is_valid(candidate):
        return basis, None
    return candidate, (
        f"Interpreted basis '{basis}' as '{candidate}' (polarization/diffuse suffixes need "
        f"parentheses, e.g. '6-31G(d)' or '6-31G*', not '6-31Gd')."
    )
