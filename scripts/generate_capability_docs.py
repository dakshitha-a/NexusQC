#!/usr/bin/env python3
"""Regenerate the capability tables in docs/QM_CAPABILITIES.md from code.

    python3 scripts/generate_capability_docs.py            # rewrite the tables
    python3 scripts/generate_capability_docs.py --check     # fail on drift

Phase 0 wrote `docs/QM_CAPABILITIES.md` by hand from real spike runs, and
Phase 1 transcribed it into `app/chemistry/registry2/capabilities.py`. From
here on the code is the source and the document is generated, because two
hand-maintained copies of the same matrix diverge -- and the direction they
diverge in is the dangerous one: the document is what a human reads when
deciding whether a capability is real, while the code is what actually
routes a user's job.

**Only the region between the generated markers is touched.** Everything
else in that file is hand-written and must survive regeneration: the
"Claims not confirmed" section, the ORCA credits-banner parser trap, the
BAGEL/MKL host note, the orbital-reuse table. Those are analysis, not
tabulation -- a generator has nothing to say about them, and silently
eating them would destroy the most valuable part of the document.

Deliberately stdlib-only, like the other scripts in here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.chemistry.registry2.capabilities import (  # noqa: E402
    CAPABILITIES, CAPABILITY_FIELDS, ENGINES, methods_for_engine,
)
from app.chemistry.registry2.tasks import TASKS, supports  # noqa: E402

DOC = REPO / "docs" / "QM_CAPABILITIES.md"

BEGIN = "<!-- BEGIN GENERATED: capability-matrix -->"
END = "<!-- END GENERATED: capability-matrix -->"

# Column headings for the capability fields, in CAPABILITY_FIELDS order.
HEADINGS = {
    "energy": "Energy",
    "excited": "Excited",
    "osc_strengths": "Osc. f",
    "gradient": "Gradient",
    "excited_gradient": "ES gradient",
    "hessian": "Hessian",
    "nac": "NAC",
    "ci_opt": "CI opt",
    "constrained_opt": "Constr. opt",
    # "How many at once", as distinct from "can it at all". A blank here is
    # never a refusal: the runner falls back to one engine invocation per
    # state or pair within the same job, so the user gets every result
    # either way. What it says is whether the wavefunction is converged once
    # or once per target.
    "multi_state_gradient": "Multi-state grad",
    "nac_multi_pair": "Multi-pair NAC",
}

ENGINE_TITLES = {
    "pyscf": "PySCF 2.14.0",
    "orca": "ORCA 6.1.1",
    "bagel": "BAGEL 1.2.2",
}


def _cell(caps, field: str) -> str:
    """One matrix cell: the value, then the evidence level in parentheses.

    A capability that is present but rests on `unverified` or `gap`
    evidence renders as a "no", because that is how `MethodCaps.has()`
    treats it -- the table must show what the router will actually do, not
    what the field literally holds.
    """
    value = getattr(caps, field)
    level = caps.level_for(field)
    if value is None or value is False:
        return f"no ({level})" if level != "unverified" else "no"
    text = value if isinstance(value, str) else "yes"
    if not caps.has(field):
        # Present in the field but untrusted -- say so explicitly rather
        # than quietly printing "yes" for something nothing will route to.
        return f"**not claimed** ({level})"
    return f"{text} ({level})"


def _engine_matrix(engine: str) -> list[str]:
    methods = methods_for_engine(engine)
    header = "| Method | " + " | ".join(HEADINGS[f] for f in CAPABILITY_FIELDS) + " |"
    rule = "|---|" + "---|" * len(CAPABILITY_FIELDS)
    lines = [header, rule]
    for method in methods:
        caps = CAPABILITIES[(engine, method)]
        cells = " | ".join(_cell(caps, f) for f in CAPABILITY_FIELDS)
        lines.append(f"| `{method}` | {cells} |")
    return lines


def _engine_evidence(engine: str) -> list[str]:
    lines = ["| Method | Capability | Level | Observed |", "|---|---|---|---|"]
    for method in methods_for_engine(engine):
        caps = CAPABILITIES[(engine, method)]
        for field in CAPABILITY_FIELDS:
            ev = caps.evidence.get(field)
            if ev is None:
                continue
            observed = ev.observed.replace("|", "\\|")
            lines.append(f"| `{method}` | {HEADINGS[field]} | `{ev.level}` | {observed} |")
    return lines


def _engine_notes(engine: str) -> list[str]:
    lines = []
    for method in methods_for_engine(engine):
        caps = CAPABILITIES[(engine, method)]
        if caps.notes:
            lines.append(f"- **`{method}`**: {caps.notes}")
    return lines


def _task_matrix() -> list[str]:
    """Which (engine, method) pairs can run which task -- the derived view.

    This table is the one nothing hand-maintains anywhere: it falls out of
    each task's `requires` predicate meeting each capability row. It is
    included in the document precisely because it is the part a reader
    would otherwise try to work out in their head and get wrong.
    """
    pairs = [(e, m) for e in ENGINES for m in methods_for_engine(e)]
    header = "| Task | " + " | ".join(f"{e}/{m}" for e, m in pairs) + " |"
    rule = "|---|" + "---|" * len(pairs)
    lines = [header, rule]
    for (task, subtype), tdef in TASKS.items():
        if tdef.master and not tdef.requires:
            continue  # a batch or a geometry set has no level of theory
        name = f"{task}/{subtype}" if subtype else task
        cells = []
        for engine, method in pairs:
            verdict = supports(engine, method, task, subtype)
            cells.append("yes" if verdict.supported else "-")
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    return lines


def render() -> str:
    out: list[str] = [
        "",
        "> **Generated from `app/chemistry/registry2/capabilities.py` by",
        "> `scripts/generate_capability_docs.py`. Do not edit inside the generated",
        "> markers. Edit the capability table in code and regenerate.**",
        "> Everything outside the markers is hand-written and is not touched.",
        "",
        "The evidence level in each cell is the level for *that cell*, not for the",
        "row: a method whose gradient was executed here and whose Hessian is only",
        "documented says so in each place, rather than rounding the whole row in",
        "one direction. A capability recorded as present but resting on",
        "`unverified` or `gap` evidence shows as **not claimed**. The routing",
        "table refuses to offer it, which is the behaviour this document has to",
        "describe.",
        "",
    ]
    for engine in ENGINES:
        out.append(f"### {ENGINE_TITLES.get(engine, engine)}")
        out.append("")
        out.extend(_engine_matrix(engine))
        out.append("")
        notes = _engine_notes(engine)
        if notes:
            out.extend(notes)
            out.append("")
        out.append("<details><summary>Per-cell evidence</summary>")
        out.append("")
        out.extend(_engine_evidence(engine))
        out.append("")
        out.append("</details>")
        out.append("")

    out.append("### Derived task availability")
    out.append("")
    out.append("Nothing hand-maintains this table. Each cell is")
    out.append("`tasks.supports()` meeting the capability row above it, so a task can")
    out.append("never be offered on an engine whose capability evidence does not carry")
    out.append("it.")
    out.append("")
    out.extend(_task_matrix())
    out.append("")
    return "\n".join(out)


def splice(existing: str, generated: str) -> str:
    if BEGIN not in existing or END not in existing:
        raise SystemExit(
            f"[FAIL] {DOC} has no generated-region markers.\n"
            f"       Add these two lines around the region to regenerate:\n"
            f"         {BEGIN}\n         {END}"
        )
    head = existing.split(BEGIN)[0]
    tail = existing.split(END, 1)[1]
    return f"{head}{BEGIN}\n{generated}\n{END}{tail}"


# --- the welcome screen's own table ------------------------------------------
#
# R-061: frontend/src/chat/WelcomeMessage.tsx carried a hand-written copy of
# engine routing, with a comment saying it "mirrors
# app/chemistry/jobs/registry.py" -- a module the registry-v2 rewrite deleted.
# Four of its twelve rows had drifted: it said BAGEL optimises only at
# CASSCF/CASPT2 (it optimises at HF too, per the registry), that BAGEL
# frequencies are HF-only (CASSCF frequencies route there as well), and it
# marked the potential-energy scan with an asterisk on all three engines
# without saying what the asterisk meant. It is the first thing a new user
# reads, so it is the worst place in the app for a stale capability claim.
#
# Generated into a JSON the frontend imports, rather than fetched at runtime:
# it is static per deployment, the frontend must render it with no backend
# (the welcome screen is what you see before anything works), and a build
# artifact keeps the drift visible in a diff.

WELCOME_JSON = REPO / "frontend" / "src" / "chat" / "capabilityRows.json"

# One row per thing a user would ask for, as (label, task, subtype, methods).
# `methods` is every level of theory the row covers: a cell then says whether
# an engine runs all of them, some of them (naming which), or none. A single
# method per row would have lost the nuance the hand-written table actually
# got right -- that BAGEL optimises only at CASSCF and CASPT2 here.
#
# Orbital visualisation is deliberately absent, because there is no task for
# it: registry2's module docstring records that orbital rendering is a
# PRESENTATION of a single point rather than a calculation of its own. The
# hand-written table listed it as a row, which is the same category error.
_WELCOME_ROWS = [
    ("Single-point energy (HF / DFT)", "single_point", "gs", ("hf", "dft")),
    ("MP2 / CCSD", "single_point", "gs", ("mp2", "ccsd")),
    ("Geometry optimisation", "opt", "min", ("hf", "dft", "mp2", "ccsd", "casscf", "caspt2")),
    ("Frequencies / thermochemistry", "freq", "", ("hf", "dft", "casscf", "caspt2")),
    ("CASSCF (incl. state-averaged)", "single_point", "gs", ("casscf",)),
    ("CASPT2 / NEVPT2", "single_point", "gs", ("caspt2", "nevpt2")),
    ("MC-PDFT / L-PDFT / CMS-PDFT", "single_point", "gs", ("mcpdft", "lpdft", "cmspdft")),
    ("Excited states (TDDFT / TDA / CIS)", "single_point", "ee", ("hf", "dft")),
    ("EOM-CCSD", "single_point", "ee", ("eom_ccsd",)),
    ("Excited-state gradients", "single_point", "grad", ("hf", "dft", "casscf")),
    ("Non-adiabatic couplings", "single_point", "nac", ("hf", "dft", "casscf")),
    ("Potential-energy scan", "pes_1d", "", ("hf", "dft", "casscf")),
    ("Conical-intersection optimisation", "opt", "ci", ("hf", "dft", "casscf")),
    ("Transition state (NEB-TS)", "neb_ts", "", ("hf", "dft")),
    ("Nuclear-ensemble spectrum", "wigner_spectra", "", ("hf", "dft")),
    ("Active-space recommendation", "cas_reco", "", ("casscf",)),
    ("Custom input file", "blind", "", (None,)),
]

_METHOD_LABELS = {
    "hf": "HF", "dft": "DFT", "mp2": "MP2", "ccsd": "CCSD", "eom_ccsd": "EOM-CCSD",
    "casscf": "CASSCF", "caspt2": "CASPT2", "nevpt2": "NEVPT2",
    "mcpdft": "MC-PDFT", "lpdft": "L-PDFT", "cmspdft": "CMS-PDFT",
}


def render_welcome_rows() -> str:
    from app.chemistry.registry2.lookup import route_engine
    from app.chemistry.registry2.tasks import supports

    rows = []
    for label, task, subtype, methods in _WELCOME_ROWS:
        per_engine: dict[str, list[str]] = {e: [] for e in ENGINES}
        defaults: set[str] = set()
        for method in methods:
            for engine in ENGINES:
                if supports(engine, method, task, subtype).supported:
                    per_engine[engine].append(method)
            if method is not None:
                defaults.add(route_engine(method, task, subtype).engine)
        cells: dict[str, str | None] = {}
        for engine in ENGINES:
            got = per_engine[engine]
            if not got:
                cells[engine] = None
            elif len(got) == len([m for m in methods]):
                cells[engine] = "default" if engine in defaults else "yes"
            else:
                # Whichever list is shorter, so a cell that supports five of
                # six methods reads "no CASPT2" rather than naming five.
                missing = [m for m in methods if m not in got]
                if len(missing) < len(got):
                    named = ", ".join(_METHOD_LABELS.get(m, str(m)) for m in missing)
                    cells[engine] = f"no {named}"
                else:
                    named = ", ".join(_METHOD_LABELS.get(m, str(m)) for m in got)
                    cells[engine] = f"{named} only"
        available = [e for e in ENGINES if cells[e] is not None]
        if len(available) == 1 and cells[available[0]] in ("yes", "default"):
            cells[available[0]] = "only option"
        rows.append({"calc": label, **cells})
    return json.dumps(rows, indent=2) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    if not DOC.exists():
        print(f"[FAIL] {DOC} does not exist")
        return 1
    existing = DOC.read_text()
    updated = splice(existing, render())
    welcome_now = WELCOME_JSON.read_text() if WELCOME_JSON.exists() else ""
    welcome_next = render_welcome_rows()
    if check:
        stale = []
        if updated != existing:
            stale.append("docs/QM_CAPABILITIES.md")
        if welcome_next != welcome_now:
            stale.append(str(WELCOME_JSON.relative_to(REPO)))
        if stale:
            print(f"[FAIL] out of date with app/chemistry/registry2/capabilities.py: "
                  f"{', '.join(stale)}")
            print("       Run: python3 scripts/generate_capability_docs.py")
            return 1
        print("[PASS] docs/QM_CAPABILITIES.md and the welcome screen's table match "
              "the capability table in code.")
        return 0
    wrote = []
    if updated != existing:
        DOC.write_text(updated)
        wrote.append(str(DOC.relative_to(REPO)))
    if welcome_next != welcome_now:
        WELCOME_JSON.write_text(welcome_next)
        wrote.append(str(WELCOME_JSON.relative_to(REPO)))
    if not wrote:
        print("[OK] already up to date.")
        return 0
    print(f"[OK] regenerated {', '.join(wrote)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
