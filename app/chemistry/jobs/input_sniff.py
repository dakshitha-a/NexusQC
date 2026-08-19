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
    ("opt", ("opt", "min")),
    ("numfreq", ("freq", "")),
    ("anfreq", ("freq", "")),
    ("freq", ("freq", "")),
    ("sp", ("single_point", "gs")),
)

# ORCA method keywords. Functionals are recognized as `dft` -- the same
# collapsing registry2 does, where the functional is a parameter rather
# than a method.
_ORCA_METHODS: tuple[tuple[str, str], ...] = (
    ("caspt2", "caspt2"),
    ("casscf", "casscf"),
    ("nevpt2", "casscf"),
    ("eom-ccsd", "eom_ccsd"),
    ("ccsd(t)", "ccsd"),
    ("ccsd", "ccsd"),
    ("ri-mp2", "mp2"),
    ("mp2", "mp2"),
    ("hf", "hf"),
)

_ORCA_FUNCTIONALS = (
    "b3lyp", "pbe0", "pbe", "blyp", "bp86", "tpss", "tpssh", "m06-2x", "m062x",
    "wb97x-d3", "wb97x-d", "wb97x", "cam-b3lyp", "b2plyp", "revpbe", "scan",
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
    "forces": ("single_point", "grad"),
    "nacme": ("single_point", "nac"),
}

_BAGEL_METHOD_TITLES: dict[str, str] = {
    "casscf": "casscf",
    "caspt2": "caspt2",
    "smith": "caspt2",     # BAGEL runs CASPT2 through its SMITH3 module
    "hf": "hf",
    "rohf": "hf",
    "uhf": "hf",
    "ks": "dft",
    "dft": "dft",
    "mp2": "mp2",
}


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


def _sniff_orca(text: str) -> SniffResult:
    keywords = _orca_keyword_line(text)
    tokens = keywords.split()
    lower = text.lower()
    reasons: list[str] = []

    task, subtype = "", ""
    # "! Opt Freq" is one job in ORCA, and reading only the first keyword
    # would call it a plain optimization and silently drop the frequencies.
    if any(t.startswith("opt") for t in tokens) and any(t.endswith("freq") for t in tokens):
        task, subtype = "opt_freq", ""
        reasons.append("the keyword line asks for both an optimization and frequencies")
    else:
        for keyword, pair in _ORCA_TASK_KEYWORDS:
            if keyword in tokens:
                task, subtype = pair
                reasons.append(f"keyword {keyword!r}")
                break

    if "%mecp" in lower:
        task, subtype = "opt", "ci"
        reasons.append("a %mecp block, i.e. a crossing-point search")
    elif "%tddft" in lower and not task:
        task, subtype = "single_point", "ee"
    if "%tddft" in lower and task == "single_point" and subtype == "gs":
        task, subtype = "single_point", "ee"
        reasons.append("a %tddft block")
    if not task:
        # ORCA's own default with no task keyword is a single point.
        task, subtype = "single_point", "gs"
        reasons.append("no task keyword, which ORCA treats as a single point")

    method = None
    for keyword, canonical in _ORCA_METHODS:
        if keyword in tokens:
            method = canonical
            reasons.append(f"method keyword {keyword!r}")
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

    method = None
    for title in titles:
        if title in _BAGEL_METHOD_TITLES:
            method = _BAGEL_METHOD_TITLES[title]
            break
    # An optimization or hessian block names its own method in a nested
    # "method" list rather than as a top-level section.
    if method is None:
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for nested in block.get("method") or []:
                nested_title = str((nested or {}).get("title", "")).lower()
                if nested_title in _BAGEL_METHOD_TITLES:
                    method = _BAGEL_METHOD_TITLES[nested_title]
                    reasons.append(f"a nested {nested_title!r} method block")
                    break
            if method:
                break

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
    elif "tdscf" in lower or "tddft" in lower or ".tda(" in lower:
        task, subtype = "single_point", "ee"
        reasons.append("a tdscf call")

    method = None
    if "mcscf" in lower or "casscf" in lower:
        method = "casscf"
    elif "cc.ccsd" in lower or "ccsd(" in lower:
        method = "ccsd"
    elif "mp.mp2" in lower or "mp2(" in lower:
        method = "mp2"
    elif "dft.rks" in lower or "dft.uks" in lower or ".ks(" in lower:
        method = "dft"
    elif "scf.rhf" in lower or "scf.uhf" in lower or "scf.rohf" in lower:
        method = "hf"

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
