"""Best-effort, mechanical correction for two parameters the LLM/user get
wrong in predictable ways: the QC method name ("hf" vs "rhf"/"uhf"/"rohf"
or a plain typo like "rfh") and Pople-style basis-set polarization/diffuse
suffixes glued on without punctuation ("6-31gd" instead of "6-31g(d)" or
"6-31g*"). The basis case is a real, previously-hit bug in this app -- see
CLAUDE.md's _kb_context_for_job note, where "6-31gd" reached PySCF
unparsed and surfaced as a bare KeyError instead of being caught earlier.
That was only ever fixed by the LLM eventually noticing the engine's own
runtime error and correcting itself over several attempts; this module
closes the gap mechanically, before a job is ever submitted, in
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

# registry2.capabilities imports nothing from this package (only dataclasses
# and typing), so naming it here cannot cycle back through jobs/.
from app.chemistry.registry2.capabilities import CANONICAL_METHODS

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


# The spellings whose only difference from their canonical form is the
# restricted/unrestricted prefix this app does not take from the user.
_REFERENCE_SPELLINGS = re.compile(r"^(r|u|ro)(hf|ks)$", re.IGNORECASE)


def _registry_resolution(method: str) -> Optional[str]:
    """What registry2 makes of this spelling, or None if it makes nothing
    of it. Canonical names and synonyms both count.

    Anything the registry already resolves is not a typo, so it is not
    this module's business to repair. That is R-004: `lpdft` is a real
    method with its own capability row, it is simply absent from the small
    `_METHOD_ALIASES` table below, and `SequenceMatcher(None, "lpdft",
    "dft").ratio()` is exactly 0.75, exactly the fuzzy cutoff. So a
    request for L-PDFT was "repaired" into plain Kohn-Sham DFT, a
    single-reference method standing in for a multireference one, and the
    note attached to the swap talked about restricted versus unrestricted
    references. Raising the cutoff would have been the wrong fix: it fixes
    one arithmetic coincidence and leaves the next one, and it weakens the
    repair this module exists for. What was missing was the question.

    Synonyms matter as much as canonical names, and `pdft` shows why. The
    registry reads it as MC-PDFT; the fuzzy match scores it 0.857 against
    `dft` and would read it as Kohn-Sham. Both are real methods, so this
    is not a spelling disagreement, it is two different calculations.
    Deferring to the registry means one authority decides, and it is the
    one with the capability table behind it.

    The check lives here rather than at the three call sites deliberately.
    A control applied to some siblings and not others is its own recurring
    defect in this repository (R-005); one refusal at the point of rewrite
    covers every caller, including ones added later.

    `registry2.lookup` imports this module at module scope, so the import
    is deferred into the call body and the answer cached. The same lazy
    import convention is already used here for pyscf.
    """
    from app.chemistry.registry2.lookup import METHOD_SYNONYMS
    q = method.lower().strip()
    if q in CANONICAL_METHODS:
        return q
    return METHOD_SYNONYMS.get(q)


def normalize_method(method: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Returns (normalized_method, note); note is None when nothing
    changed, including when `method` doesn't resemble anything recognized
    (left untouched for the existing "Unsupported method" error to
    handle).

    A method the registry already knows is returned untouched before any
    repair is attempted. That guard closes R-004, where asking for L-PDFT
    silently ran plain DFT: `lpdft` is not a key in `_METHOD_ALIASES` (the
    table holds only spelling variants of `hf` and `dft`), so it fell
    through to the fuzzy fallback, and `SequenceMatcher(None, "lpdft",
    "dft").ratio()` is exactly 0.75, exactly the cutoff. `tddft` collapsed
    to `dft` and `hfx` to `hf` by the same arithmetic. Raising the cutoff
    would have been the wrong fix twice over: it would leave the next
    method whose name happens to score high just as exposed, and it would
    weaken the typo repair this module exists for. The real defect was
    that nothing asked "is this already a method?" first. `registry2.
    lookup.resolve_method` does ask, one call earlier in its own flow
    (`if q in CANONICAL_METHODS`), which is exactly why the bug was
    invisible through that path and live through the draft path.

    The check lives here rather than at the call sites deliberately. There
    are three callers (`agent/tools.py`'s `_build_spec_or_error`,
    `registry2/lookup.py`, and anything added later), and a control
    applied at some call sites and not others is its own recurring bug in
    this repository (R-005). One authoritative refusal at the point of
    rewrite covers all of them.
    """
    if not method:
        return method, None
    known = _registry_resolution(method)
    if known is not None:
        if known == method.lower().strip():
            return known, None
        # The registry resolving its own vocabulary is not a correction,
        # so this says what the word was read as and stops. The one thing
        # worth adding is for the RHF/UHF/ROHF family, where the answer to
        # "why did my choice disappear?" is that this app picks the
        # reference from the molecule's spin and never from this field.
        note = f"Read '{method}' as '{known}'."
        if _REFERENCE_SPELLINGS.match(method.strip()):
            note += (" Restricted versus unrestricted reference is chosen automatically from the "
                     "molecule's spin here, not from this parameter.")
        return known, note
    key = re.sub(r"[^a-z]", "", method.lower())
    canonical = _METHOD_ALIASES.get(key)
    exact_alias = canonical is not None
    if canonical is None:
        # Tight cutoff, single best match only -- catches an unlisted typo
        # (e.g. a stray/dropped letter) without ever coercing a genuinely
        # different method name (mp2, ccsd, casscf, ...) into hf/dft.
        close = difflib.get_close_matches(key, _METHOD_ALIASES.keys(), n=1, cutoff=0.75)
        canonical = _METHOD_ALIASES[close[0]] if close else None
    if canonical is None or canonical == method.lower():
        return method, None
    # Two different things happen here and they deserve two different
    # sentences. Collapsing rks/roks onto their parent is a statement
    # about how this app models the reference; repairing "rfh" is a
    # statement about spelling. The single note this used to return said
    # the first thing in both cases, which is how R-004's silent method
    # substitution arrived wearing an explanation that was true,
    # reassuring, and about a different subject.
    if exact_alias:
        note = f"Read '{method}' as '{canonical}'."
        if _REFERENCE_SPELLINGS.match(method.strip()):
            note += (" Restricted versus unrestricted reference is chosen automatically from the "
                     "molecule's spin here, not from this parameter.")
    else:
        note = f"Read '{method}' as a misspelling of '{canonical}'."
    return canonical, note


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
    from app.chemistry.jobs.bse_basis import is_bse_ref

    if is_bse_ref(basis):
        return basis, None  # already an exact, resolved Basis Set Exchange choice -- nothing to typo-correct
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


def normalize_functional(
    functional: Optional[str], engine: Optional[str]
) -> tuple[Optional[str], Optional[str], tuple[str, ...]]:
    """Returns (functional, note, menu_options), the third element being
    names to offer when there is a genuine choice to make.

    The counterpart of `normalize_basis` above, and the reason this module
    is no longer only about typos. A functional name is the one parameter
    where being wrong does not necessarily fail: PySCF will happily compute
    with `MGGA_X_R2SCAN`, half of r2SCAN, and converge 0.32 Eh from the
    answer without a word of complaint. So this does not merely repair
    spelling, it refuses names that are not whole functionals.

    Conservative in the same way `normalize_basis` is. A name the engine
    already accepts is returned untouched -- second-guessing a correct
    choice is worse than doing nothing. A rewrite is only ever emitted when
    the result passes every check in `functional.py`, and it always carries
    a note, so the change is visible on the approval card before the job
    runs. Where the request is genuinely ambiguous -- a bare `-d3` on
    PySCF, where D3(BJ) and D3(zero) are different chemistry -- nothing is
    chosen and the options are handed back for the user to pick from. This
    module never guesses at different chemistry than was asked for.
    """
    if not functional or not engine:
        return functional, None, ()
    from app.chemistry.jobs import functional as functional_lookup

    result = functional_lookup.resolve_functional(functional, engine)
    if result.status == functional_lookup.REWRITE:
        return result.resolved, result.note, ()
    if result.status in (functional_lookup.AMBIGUOUS, functional_lookup.UNSUPPORTED_HERE):
        return functional, result.note, result.options
    # exact, or nothing close enough to offer honestly -- leave it alone and
    # let the existing menu/elicitation path handle it as before.
    return functional, None, ()
