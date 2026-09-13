#!/usr/bin/env python3
"""A method the registry already knows is never rewritten by typo repair.
Regression test for R-004 (and the class it belongs to).

    PYTHONPATH=$PWD python3 tests/backend/draft_02_canonical_method_survives.py

R-004: asking for L-PDFT silently ran plain DFT. `param_normalize.
normalize_method` exists to repair typos, and it does that with a fuzzy
match against a small alias table holding only the spelling variants of
`hf` and `dft`. `SequenceMatcher(None, "lpdft", "dft").ratio()` is exactly
0.75, which is exactly the cutoff, so `lpdft` was "repaired" into `dft`.
The user asked for a multireference pair-density calculation, got a
single-reference Kohn-Sham one, and was told only that the
restricted/unrestricted reference is chosen automatically -- a true
sentence about a different subject. `tddft` collapsed to `dft` and `hfx`
to `hf` the same way.

The bug is not the ratio, it is the missing question. `lpdft` is a real
entry in `registry2.capabilities.CANONICAL_METHODS`; nothing asked whether
the input was already a known method before trying to repair it. Its
sibling `registry2.lookup.resolve_method` asks exactly that
(`if q in CANONICAL_METHODS`) one call earlier in the same flow, which is
why the bug is invisible through that path and live through the draft path.

So this script checks the property rather than the one string:

1. Every canonical method, and every alias in the table, survives
   `normalize_method` unchanged, with no note attached. This is the
   general statement; `lpdft` and `tddft` are two of its cases.
2. A genuine typo of a canonical name is still repaired, so the check
   above is not passing because repair was simply switched off. `rfh`
   (the transposition the module was written for) must still become `hf`.
3. A real method name reaches a built JobSpec intact, which is the thing
   a user would actually notice. `_build_spec_or_error` is the shared
   entry point every ready draft goes through, and it is called here for
   an L-PDFT single point with active-space parameters. The resulting
   spec's `method` must be `lpdft` and the active-space parameters must
   still be on it.

Runs entirely in process: no server, no database, no engine.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

from app.chemistry.jobs.param_normalize import _METHOD_ALIASES, normalize_method  # noqa: E402
from app.chemistry.registry2.capabilities import CANONICAL_METHODS  # noqa: E402

print("R-004: a canonical method name is not a typo\n")

print("1. every canonical method survives normalize_method untouched")
for m in CANONICAL_METHODS:
    got, note = normalize_method(m)
    check(f"normalize_method({m!r}) leaves it alone",
          got == m and note is None,
          f"got {got!r}",
          f"rewritten to {got!r} with note {note!r}")

print("\n   and so does every alias the table itself declares")
for alias, canonical in sorted(_METHOD_ALIASES.items()):
    got, _note = normalize_method(alias)
    check(f"normalize_method({alias!r}) -> {canonical!r}", got == canonical, f"got {got!r}")

print("\n1b. a synonym the registry knows resolves the registry's way, not the fuzzy way")
# `pdft` is the case that makes this more than a restatement of (1). The
# registry reads it as MC-PDFT; the fuzzy match scores it 0.857 against
# `dft` and would read it as Kohn-Sham. Two real methods, so this is not a
# spelling disagreement.
for spelled, want in (("pdft", "mcpdft"), ("l-pdft", "lpdft"), ("tddft", "dft"),
                      ("cms", "cmspdft"), ("sa-casscf", "casscf")):
    got, _note = normalize_method(spelled)
    check(f"normalize_method({spelled!r}) -> {want!r}", got == want, f"got {got!r}")

print("\n2. genuine typos are still repaired (repair is not switched off)")
for typo, want in (("rfh", "hf"), ("hartree fock", "hf"), ("kohn-sham", "dft"),
                   ("UHF", "hf"), ("hfx", "hf")):
    got, note = normalize_method(typo)
    check(f"normalize_method({typo!r}) -> {want!r}", got == want,
          f"got {got!r}", f"got {got!r}, note {note!r}")

print("\n3. an L-PDFT draft builds a spec that is still L-PDFT")
from app.agent.tools import _build_spec_or_error  # noqa: E402
from app.chemistry.molecule import resolve_molecule  # noqa: E402

mol = resolve_molecule("water").to_dict()
spec, _preview, _kb, notes, _scan, _kw, _warn, err = _build_spec_or_error(
    task="single_point", subtype="ee", molecule=mol, engine="pyscf", method="lpdft",
    raw_params={"basis": "sto-3g", "active_electrons": 4, "active_orbitals": 4,
                "n_states": 2, "on_functional": "tPBE"},
)
check("the draft builds without an error", err is None, f"err={err!r}")
if spec is not None:
    check("spec.method is 'lpdft', not 'dft'", spec.method == "lpdft", f"method={spec.method!r}")
    check("the active space survived the build",
          spec.params.get("active_electrons") == 4 and spec.params.get("active_orbitals") == 4,
          f"active_electrons={spec.params.get('active_electrons')}, "
          f"active_orbitals={spec.params.get('active_orbitals')}")
    check("no parameter note claims the method was reinterpreted",
          not any("nterpreted method" in n for n in (notes or [])),
          f"{len(notes or [])} note(s)", f"notes={notes!r}")

print("\n4. R-085: a misrouted geometry key does not silently swallow its neighbours")
# `update_job_draft`'s misrouted branch returns no `job_draft`, so the
# locally built draft is discarded whole. Its message used to name only
# the geometry key, which reads as though the rest of the call was kept.
import inspect  # noqa: E402
from app.agent import tools as _tools  # noqa: E402

src = inspect.getsource(_tools.update_job_draft.func)
misrouted_branch = src[src.index("if misrouted:"):]
check("the misrouted branch says the other keys were not recorded either",
      "not recorded" in misrouted_branch and "half-applied update" in misrouted_branch,
      "", "the branch still names only the geometry key")
check("its wording matches the unknown-key branch's established rule",
      "half-applied update is harder to reason about than none" in misrouted_branch,
      "", "the two refusals still disagree about what they did")

summary()
