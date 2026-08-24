"""Recognize a pasted engine input without running it.

A user who already has an ORCA or BAGEL input wants to run *that*, not to
answer twenty questions until the app rebuilds something like it. But an
input the app cannot read is also an input whose results it cannot parse,
preview or plot -- so the useful thing is to recognize what was pasted and
let the user choose: run it verbatim as a blind job, or have the equivalent
structured job built, which gets the previews and the result parsing.

This module does the recognizing. It is **purely mechanical** -- pattern
matching over the text, no model involved -- for the same reason
`registry2/lookup.py` exists: a model asked "what kind of ORCA input is
this?" will answer plausibly and sometimes wrongly, and a wrong answer here
silently runs a different calculation than the user pasted.

Three engines, two of which can be executed:

- **ORCA** -- a `!` keyword line, `%block ... end` sections, `* xyz` or
  `*xyzfile` geometry blocks.
- **BAGEL** -- JSON with a top-level `"bagel"` array of titled sections.
- **PySCF** -- a Python script. **Recognized and never executed.** Running
  it would mean executing user-supplied Python, which this app does not do
  at any confidence level; the useful response is to offer to build the
  equivalent structured job. This is a recorded product decision, not a
  limitation of the classifier.

Confidence is reported, not assumed. A confident classification is offered
as a structured job; an unconfident one still runs blind on a user-stated
engine, because "I cannot tell what this is" is a reason to stop guessing,
not a reason to refuse the user's own input.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

# ORCA keyword -> (task, subtype). Ordered: the first match on the `!` line
# wins, so a combined "! Opt Freq" resolves to opt_freq rather than to
# whichever of the two appears first in the text.
_ORCA_TASK_KEYWORDS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("optfreq", ("opt_freq", "")),
    ("neb-ts", ("neb_ts", "")),
    ("neb-ci", ("neb_ts", "")),
    ("neb", ("neb_ts", "")),
    ("engrad", ("single_point", "grad")),
    ("numgrad", ("single_point", "grad")),
    ("numfreq", ("freq", "")),
    ("anfreq", ("freq", "")),
    ("freq", ("freq", "")),
    ("sp", ("single_point", "gs")),
)

# ORCA spells the convergence level into the optimization keyword itself
# -- TightOpt, VeryTightOpt, LooseOpt -- and the coordinate system too
# (COpt, ZOpt, L-Opt). All of them are the same job, so the token is
# matched by its tail rather than enumerated; the alternative was a plain
# `"opt" in tokens`, which read `! TightOpt` as an input with no task
# keyword at all and therefore as a single point.
_ORCA_OPT_TOKEN = re.compile(r"^[\w-]*opt$", re.I)

# The exceptions to that tail match. A transition-state search is a real
# ORCA job and is NOT a minimum optimization, and this app has no task
# for one -- claiming opt/min here would offer to build something that
# relaxes the structure off the saddle point the user was looking for.
# Left unrecognized, which is what "I cannot tell what this is" is for.
_ORCA_NOT_MIN_OPT = ("optts", "opt-ts", "scants", "irc")

# ORCA method keywords. Functionals are recognized as `dft` -- the same
# collapsing registry2 does, where the functional is a parameter rather
# than a method.
# Matched against each token as a whole word OR as the tail of a
# hyphenated one, so the approximation families ORCA spells as prefixes --
# RI-MP2, DLPNO-CCSD(T), SC-NEVPT2, FIC-NEVPT2 -- resolve to the method
# they approximate without a row each. Order is precedence: the first
# entry that matches any token wins, so ("ccsd(t)", ...) has to precede
# ("ccsd", ...) and the EOM/STEOM families have to precede both, or a
# STEOM-DLPNO-CCSD input would come back as plain coupled cluster.
_ORCA_METHODS: tuple[tuple[str, str], ...] = (
    ("steom-ccsd", "eom_ccsd"),
    ("eom-ccsd", "eom_ccsd"),
    ("caspt2", "caspt2"),
    ("casscf", "casscf"),
    ("nevpt2", "casscf"),
    ("ccsd(t1)", "ccsd"),
    ("ccsd(t)", "ccsd"),
    ("ccsd", "ccsd"),
    ("mp2", "mp2"),
    ("hf-3c", "hf"),
    ("rohf", "hf"),
    ("uhf", "hf"),
    ("rhf", "hf"),
    ("hf", "hf"),
)

# STEOM's family names put the approximation in the middle rather than at
# the front -- STEOM-DLPNO-CCSD -- so neither the whole-token nor the
# hyphenated-tail rule above reaches it, and the tail rule would resolve
# it to plain coupled cluster. Checked first, on the token as a whole.
_ORCA_STEOM = re.compile(r"^steom-", re.I)

# Functional names, collapsed to `dft` -- the same thing registry2 does,
# where the functional is a parameter of the method rather than a method.
# Not a validation list: `param_normalize` and `keyword_suggest` already
# own that, and this only has to notice that a token is one.
_ORCA_FUNCTIONALS = (
    "b3lyp", "b3lyp/g", "b3pw91", "pbe0", "pbe", "revpbe", "rpbe", "blyp", "bp86",
    "olyp", "pw6b95", "mpw1pw", "tpss", "tpssh", "tpss0", "revtpss", "scan",
    "r2scan", "r2scan0", "m06", "m06l", "m06-l", "m06-2x", "m062x", "m06-hf",
    "mn15", "mn15-l", "cam-b3lyp", "lc-blyp", "b2plyp", "b2gp-plyp",
    "dsd-blyp", "dsd-pbep86", "x3lyp", "hse06", "b1lyp", "bhandhlyp",
)

# Composite methods and the wB97/B97 family, which are DFT but do not
# enumerate usefully: ORCA ships r2SCAN-3c, B97-3c, PBEh-3c, and a wB97
# family whose members differ by suffix (-D3, -D4, -V, -X-D3BJ, M-V).
# A trailing "-3c" alone would also catch HF-3c, which is not DFT, so
# that one is named in _ORCA_METHODS above and matched first.
_ORCA_FUNCTIONAL_PATTERNS = (
    re.compile(r"^(w|omega)?b97", re.I),
    re.compile(r"-3c$", re.I),
)

# Basis-set shapes, matched on the `!` line. Deliberately a pattern rather
# than a list: the Basis Set Exchange knows thousands of names and this
# only has to spot the token, not validate it -- `param_normalize` and
# `keyword_suggest` already own validation.
_BASIS_PATTERNS = (
    re.compile(r"^(sto-\d+g|3-21g|6-31\+{0,2}g(\(.+?\)|\*{1,2})?|6-311\+{0,2}g(\(.+?\)|\*{1,2})?)$", re.I),
    re.compile(r"^(cc-p[vw]\d?[dtq5z]z(-\w+)?|aug-cc-p[vw][dtq5z]z(-\w+)?)$", re.I),
    re.compile(r"^(def2-(sv|svp|svpd|tzvp|tzvpp|tzvppd|qzvp|qzvpp)|ma-def2-\w+)$", re.I),
)

# BAGEL section titles -> (task, subtype).
_BAGEL_TITLES: dict[str, tuple[str, str]] = {
    "optimize": ("opt", "min"),
    "hessian": ("freq", ""),
    # "forces" holds a list of gradients to evaluate; "force" is the
    # singular form for one. Both are real BAGEL section titles and both
    # are a gradient job.
    "forces": ("single_point", "grad"),
    "force": ("single_point", "grad"),
    "nacme": ("single_point", "nac"),
}

# BAGEL method section titles, in precedence order: highest level of
# theory first. Order matters here in a way it does not for ORCA, because
# a BAGEL input is a script rather than a declaration. A CASSCF run opens
# with an "hf" block, since the SCF orbitals are the starting guess; a
# CASPT2 run carries a "casscf" block ahead of "smith" for the same
# reason. Reading whichever method-shaped title appears first therefore
# reports the scaffolding instead of the calculation -- a state-averaged
# CASSCF input read as an HF single point, which is the defect
# docs/trackers/2026-08-bagel-blind-input.md opens on. Choosing by this
# order rather than by position in the text is what makes "the highest
# level of theory present is the one being run" mechanical.
_BAGEL_METHOD_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("smith", "caspt2"),   # BAGEL runs CASPT2 through its SMITH3 module
    ("caspt2", "caspt2"),
    ("casscf", "casscf"),
    ("mp2", "mp2"),
    ("ks", "dft"),
    ("dft", "dft"),
    ("rohf", "hf"),
    ("uhf", "hf"),
    ("hf", "hf"),
)

_BAGEL_METHOD_TITLES: dict[str, str] = dict(_BAGEL_METHOD_PRECEDENCE)

# The method sections whose root count means excited states. On BAGEL a
# multireference "nstate" counts the ground state too, so two or more
# roots is an excited-state calculation and exactly one is not.
_BAGEL_MULTIREFERENCE = ("casscf", "caspt2")


@dataclass(frozen=True)
class SniffResult:
    """What a pasted input appears to be.

    `executable` is the product decision, kept separate from `engine` so a
    caller cannot accidentally read "we know what this is" as "we may run
    it": a PySCF script is recognized perfectly well and still must never
    be executed.
    """
    engine: Optional[str] = None
    task: str = ""
    subtype: str = ""
    method: Optional[str] = None
    basis: Optional[str] = None
    confident: bool = False
    executable: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def task_name(self) -> str:
        return f"{self.task}/{self.subtype}" if self.subtype else self.task

    def describe(self) -> str:
        """One sentence, for the agent to relay."""
        if self.engine is None:
            return ("This does not look like an ORCA or BAGEL input, or a PySCF "
                    "script. Ask the user which engine it is for.")
        if not self.confident:
            return (f"This looks like {self.engine.upper()} input, but its calculation "
                    f"type could not be identified.")
        level = self.method or "an unidentified method"
        if self.basis:
            level = f"{level}/{self.basis}"
        return (f"This is {self.engine.upper()} input for a {self.task_name} "
                f"calculation at {level}.")

    def to_dict(self) -> dict:
        return {
            "engine": self.engine, "task": self.task, "subtype": self.subtype,
            "method": self.method, "basis": self.basis, "confident": self.confident,
            "executable": self.executable, "reasons": list(self.reasons),
        }


# ------------------------------------------------------------ engine guess

def _looks_like_bagel(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return False
    try:
        return isinstance(json.loads(text).get("bagel"), list)
    except Exception:
        # A truncated or hand-edited BAGEL input is still recognizably one.
        return '"bagel"' in text


def _looks_like_pyscf(text: str) -> bool:
    return bool(re.search(r"^\s*(import\s+pyscf|from\s+pyscf\b)", text, re.M))


def _looks_like_orca(text: str) -> bool:
    if re.search(r"^\s*!", text, re.M):
        return True
    if re.search(r"^\s*%\w+", text, re.M) and re.search(r"^\s*end\s*$", text, re.M | re.I):
        return True
    return bool(re.search(r"^\s*\*\s*(xyz|xyzfile|int)\b", text, re.M | re.I))


# ------------------------------------------------------------------- ORCA

def _orca_keyword_line(text: str) -> str:
    """The `!` keyword line(s), lowercased and joined. ORCA allows several."""
    return " ".join(m.group(1).lower()
                    for m in re.finditer(r"^\s*!\s*(.*)$", text, re.M))


def _orca_block_body(text: str, name: str) -> str:
    """The text of a `%name` block, lowercased. Bounded by the next line
    that opens a block (`%...`) or the geometry (`*...`) rather than by a
    matching `end`, because ORCA blocks nest -- `%casscf ... rel ... end
    end` -- and a keyword search does not need the exact extent, only a
    region that cannot run into the next block."""
    lower = text.lower()
    start = lower.find(f"%{name}")
    if start < 0:
        return ""
    rest = lower[start + len(name) + 1:]
    stop = re.search(r"^\s*[%*]", rest, re.M)
    return rest[:stop.start()] if stop else rest


def _orca_root_count(text: str) -> int:
    """`nroots` inside the `%casscf` block. ORCA states the root count
    there for CASSCF and for the NEVPT2 built on it, and unlike `%tddft`
    -- whose presence alone means excited states -- a `%casscf` block is
    equally the way a plain ground-state CAS calculation is written. The
    count includes the ground state, the same convention BAGEL's `nstate`
    uses (see _bagel_root_count)."""
    m = re.search(r"\bnroots\s+(\d+)", _orca_block_body(text, "casscf"))
    return int(m.group(1)) if m else 1


def _sniff_orca(text: str) -> SniffResult:
    keywords = _orca_keyword_line(text)
    tokens = keywords.split()
    lower = text.lower()
    reasons: list[str] = []

    opt_tokens = [t for t in tokens
                  if _ORCA_OPT_TOKEN.match(t) and t not in _ORCA_NOT_MIN_OPT]
    freq_tokens = [t for t in tokens if t.endswith("freq")]

    # A transition-state search is a real ORCA job that this app has no
    # task for, and it is not one either half of "! OptTS Freq" describes
    # -- reading that line as a plain frequency job silently drops the
    # search it is really doing. Reported as unidentified, which still
    # runs the input verbatim; see this module's docstring on why an
    # unconfident result is not a refusal.
    ts_tokens = [t for t in tokens if t in _ORCA_NOT_MIN_OPT]
    if ts_tokens:
        return SniffResult(
            engine="orca", executable=True, confident=False,
            basis=next((t for t in tokens if _is_basis_token(t)), None),
            reasons=(f"keyword {ts_tokens[0]!r}, a transition-state search, which this "
                     f"app has no job type for",),
        )

    task, subtype = "", ""
    # "! Opt Freq" is one job in ORCA, and reading only the first keyword
    # would call it a plain optimization and silently drop the frequencies.
    if opt_tokens and freq_tokens:
        task, subtype = "opt_freq", ""
        reasons.append("the keyword line asks for both an optimization and frequencies")
    else:
        for keyword, pair in _ORCA_TASK_KEYWORDS:
            if keyword in tokens:
                task, subtype = pair
                reasons.append(f"keyword {keyword!r}")
                break
        if not task and opt_tokens:
            task, subtype = "opt", "min"
            reasons.append(f"keyword {opt_tokens[0]!r}")

    if "%mecp" in lower:
        task, subtype = "opt", "ci"
        reasons.append("a %mecp block, i.e. a crossing-point search")
    # %cis is ORCA's other name for the same block, and configures the
    # same module -- an input using it is as much an excited-state
    # calculation as one using %tddft.
    excited_block = next((b for b in ("%tddft", "%cis") if b in lower), None)
    if excited_block and not task:
        task, subtype = "single_point", "ee"
    if excited_block and task == "single_point" and subtype == "gs":
        task, subtype = "single_point", "ee"
        reasons.append(f"a {excited_block} block")
    if not task:
        # ORCA's own default with no task keyword is a single point.
        task, subtype = "single_point", "gs"
        reasons.append("no task keyword, which ORCA treats as a single point")

    method = None
    if any(_ORCA_STEOM.match(tok) for tok in tokens):
        method = "eom_ccsd"
        reasons.append("a STEOM-CCSD family keyword")
    for keyword, canonical in _ORCA_METHODS:
        if method:
            break
        hit = next((t for t in tokens if t == keyword or t.endswith("-" + keyword)), None)
        if hit:
            method = canonical
            reasons.append(f"method keyword {hit!r}")
            break
    if method is None and "%casscf" in lower:
        method = "casscf"
        reasons.append("a %casscf block")
    if method is None:
        for functional in _ORCA_FUNCTIONALS:
            if functional in tokens:
                method = "dft"
                reasons.append(f"the functional {functional!r}")
                break
    if method is None:
        hit = next((t for t in tokens
                    if any(p.search(t) for p in _ORCA_FUNCTIONAL_PATTERNS)), None)
        if hit:
            method = "dft"
            reasons.append(f"the functional {hit!r}")

    # A multireference input states how many states it is averaging over
    # and says nothing else about being an excited-state calculation --
    # there is no %tddft block to spot. Same reading, same threshold and
    # the same gs-only promotion as the BAGEL branch below: %mecp and a
    # NAC input both carry several roots and are neither of them a set of
    # vertical excitation energies.
    if task == "single_point" and subtype == "gs" and method == "casscf":
        n_roots = _orca_root_count(text)
        if n_roots > 1:
            subtype = "ee"
            reasons.append(f"nroots {n_roots}, i.e. more roots than the ground state alone")

    # EOM-CCSD and STEOM-CCSD have nothing to compute except transitions
    # out of the coupled-cluster ground state, so unlike a CASSCF input
    # there is no root count to consult -- naming the method is already
    # saying "excited states".
    if task == "single_point" and subtype == "gs" and method == "eom_ccsd":
        subtype = "ee"
        reasons.append("an EOM-CCSD family method, which computes excitation energies")

    basis = next((t for t in tokens if _is_basis_token(t)), None)
    if basis:
        reasons.append(f"basis {basis!r}")

    return SniffResult(
        engine="orca", task=task, subtype=subtype, method=method, basis=basis,
        confident=bool(task and method), executable=True, reasons=tuple(reasons),
    )


def _is_basis_token(token: str) -> bool:
    return any(p.match(token) for p in _BASIS_PATTERNS)


# ------------------------------------------------------------------ BAGEL

def _bagel_root_count(blocks: list) -> int:
    """The largest `nstate` anywhere in the input, top-level sections and
    nested "method" lists alike. Largest rather than first because a
    CASPT2 input states it twice (once in `casscf`, once in `smith`) and
    a truncated or hand-edited one may state it in only one of them."""
    best = 1
    def _scan(block) -> None:
        nonlocal best
        if not isinstance(block, dict):
            return
        value = block.get("nstate")
        if isinstance(value, int) and value > best:
            best = value
        nested = block.get("method")
        for sub in (nested or []) if not isinstance(nested, str) else ():
            _scan(sub)
    for block in blocks:
        _scan(block)
    return best


def _sniff_bagel(text: str) -> SniffResult:
    reasons: list[str] = []
    try:
        blocks = json.loads(text)["bagel"]
    except Exception:
        return SniffResult(engine="bagel", executable=True, confident=False,
                           reasons=("the JSON could not be parsed, so only the engine "
                                    "is known",))
    titles = [str(b.get("title", "")).lower() for b in blocks if isinstance(b, dict)]
    reasons.append("sections: " + ", ".join(t for t in titles if t))

    task, subtype = "", ""
    for title in titles:
        if title in _BAGEL_TITLES:
            task, subtype = _BAGEL_TITLES[title]
            break
    if task == "opt":
        for block in blocks:
            if isinstance(block, dict) and str(block.get("opttype", "")).lower() == "conical":
                task, subtype = "opt", "ci"
                reasons.append("opttype 'conical', i.e. a crossing-point search")
                break
    if not task:
        task, subtype = "single_point", "gs"
        reasons.append("no optimize/hessian/forces/nacme section, so a single point")

    # An optimization, forces or hessian block names its own method in a
    # nested "method" list rather than as a top-level section, so both
    # levels are collected before anything is chosen -- picking from the
    # top level first would let a bare "hf" preamble outrank the nested
    # block that says what the job actually computes.
    method_titles: list[str] = [t for t in titles if t in _BAGEL_METHOD_TITLES]
    nested_titles: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        # "method" is a list of blocks under optimize/forces/hessian, but
        # a plain string under "smith" ({"title": "smith", "method":
        # "caspt2"}) -- both shapes appear in inputs this app builds, so
        # neither may raise here.
        nested_methods = block.get("method")
        if isinstance(nested_methods, str):
            nested_methods = [{"title": nested_methods}]
        for nested in nested_methods or []:
            if not isinstance(nested, dict):
                continue
            nested_title = str(nested.get("title", "")).lower()
            if nested_title in _BAGEL_METHOD_TITLES:
                nested_titles.append(nested_title)
    method = None
    for title, canonical in _BAGEL_METHOD_PRECEDENCE:
        if title in method_titles:
            method = canonical
            reasons.append(f"a {title!r} section, the highest level of theory present")
            break
        if title in nested_titles:
            method = canonical
            reasons.append(f"a nested {title!r} method block")
            break

    # BAGEL has no keyword that says "excited state" the way ORCA's
    # %tddft block does. On a multireference method the root count is the
    # only thing separating one ground-state energy from a set of
    # vertical excitation energies, and it counts the ground state, so
    # the threshold is more than one -- the same reading of n_states the
    # scan drafts use (docs/trackers/2026-08-excited-state-scans.md).
    # Promoted only from single_point/gs, mirroring the ORCA branch
    # above: a nacme block carries several roots too and is a coupling,
    # not a set of excitation energies.
    if task == "single_point" and subtype == "gs" and method in _BAGEL_MULTIREFERENCE:
        n_roots = _bagel_root_count(blocks)
        if n_roots > 1:
            subtype = "ee"
            reasons.append(f"nstate {n_roots}, i.e. more roots than the ground state alone")

    basis = None
    for block in blocks:
        if isinstance(block, dict) and block.get("basis"):
            basis = str(block["basis"])
            reasons.append(f"basis {basis!r}")
            break

    return SniffResult(
        engine="bagel", task=task, subtype=subtype, method=method, basis=basis,
        confident=bool(task and method), executable=True, reasons=tuple(reasons),
    )


# ------------------------------------------------------------------ PySCF

def _pyscf_root_count(text: str) -> int:
    """How many states a PySCF multireference script solves for. Two
    idioms say it: an explicit `nroots = N` (on the CASSCF object or its
    fcisolver), and any form of `state_average`, which means more than
    one state by construction whether or not the weights are visible to a
    regex. Counts the ground state, matching the convention BAGEL's
    `nstate` and ORCA's `nroots` use."""
    counts = [int(m) for m in re.findall(r"\bnroots\s*=\s*(\d+)", text)]
    best = max(counts) if counts else 1
    if "state_average" in text.lower():
        best = max(best, 2)
    return best


def _sniff_pyscf(text: str) -> SniffResult:
    lower = text.lower()
    reasons = ["a pyscf import"]
    task, subtype = "single_point", "gs"
    if "optimizer" in lower or "geometric_solver" in lower or "berny_solver" in lower:
        task, subtype = "opt", "min"
        reasons.append("a geometry optimizer call")
    elif "hessian" in lower or "harmonic_analysis" in lower:
        task, subtype = "freq", ""
        reasons.append("a Hessian call")
    elif any(m in lower for m in ("tdscf", "tddft", ".tda(", ".tdhf(", ".tddft(")):
        task, subtype = "single_point", "ee"
        reasons.append("a tdscf call")

    # Ordered highest level of theory first, for the same reason the BAGEL
    # table is: a PySCF script builds the cheap object before the
    # expensive one that wraps it, so `mf = scf.RHF(mol)` sits above
    # `mc = mcscf.CASSCF(mf, ...)` in almost every CASSCF script ever
    # written. Reading whichever appeared first would report the starting
    # guess. Matched as substrings, since a script may spell the same
    # class as `pyscf.mcscf.CASSCF`, `mcscf.CASSCF` or `mf.CASSCF`.
    method = None
    for markers, canonical in (
        (("eom_ccsd", "eomee", "eomip", "eomea", ".eomee", "eom-ccsd"), "eom_ccsd"),
        (("nevpt2", "mrpt"), "casscf"),
        (("mcscf", "casscf", "casci", "avas", "state_average"), "casscf"),
        (("cc.ccsd", "ccsd(", ".ccsd(", "cc.rccsd", "cc.uccsd"), "ccsd"),
        (("mp.mp2", "mp2(", ".mp2(", "dfmp2"), "mp2"),
        (("dft.rks", "dft.uks", "dft.roks", ".ks(", ".rks(", ".uks(", ".roks("), "dft"),
        (("scf.rhf", "scf.uhf", "scf.rohf", ".rhf(", ".uhf(", ".rohf(", "scf.hf"), "hf"),
    ):
        hit = next((m for m in markers if m in lower), None)
        if hit:
            method = canonical
            reasons.append(f"{hit!r} in the script")
            break

    # The same two promotions the executable engines get, so a user who
    # pastes a script and accepts the offer to have the equivalent job
    # built is offered the calculation their script performs. Neither
    # fires on anything but a ground-state single point, so an optimizer
    # or a Hessian script keeps its own task.
    if task == "single_point" and subtype == "gs" and method == "casscf":
        n_roots = _pyscf_root_count(text)
        if n_roots > 1:
            subtype = "ee"
            reasons.append(f"{n_roots} roots, i.e. more than the ground state alone")
    if task == "single_point" and subtype == "gs" and method == "eom_ccsd":
        subtype = "ee"
        reasons.append("an EOM-CCSD solver, which computes excitation energies")

    basis = None
    m = re.search(r"basis\s*=\s*['\"]([^'\"]+)['\"]", text)
    if m:
        basis = m.group(1)
        reasons.append(f"basis {basis!r}")

    return SniffResult(
        engine="pyscf", task=task, subtype=subtype, method=method, basis=basis,
        confident=bool(task and method),
        # The whole point. Recognized, never run -- see the module docstring.
        executable=False,
        reasons=tuple(reasons) + (
            "a PySCF script is never executed as pasted; offer to build the "
            "equivalent structured job instead",),
    )


# ------------------------------------------------------------------- entry

def sniff(text: Optional[str]) -> SniffResult:
    """Classify a pasted engine input. Never raises, never executes."""
    if not text or not text.strip():
        return SniffResult(reasons=("the text was empty",))
    # BAGEL first: its inputs are JSON, and JSON containing a `!` inside a
    # string would otherwise read as an ORCA keyword line.
    if _looks_like_bagel(text):
        return _sniff_bagel(text)
    if _looks_like_pyscf(text):
        return _sniff_pyscf(text)
    if _looks_like_orca(text):
        return _sniff_orca(text)
    return SniffResult(reasons=("no ORCA keyword line, BAGEL JSON or PySCF import "
                                "was found",))
