"""Which engine runs a job when the user did not name one.

Two layers, in this order:

1. **Hard rules** -- routing decisions that are properties of this
   deployment rather than of a preference. CASPT2 exists on exactly one
   engine here, and CASSCF oscillator strengths on exactly one other, so
   those are not choices to be made by preference order or by the model
   inferring intent. They are mechanical, which is the point: the legacy
   `default_engine()` already routed `casscf + want_oscillator_strengths`
   to ORCA in code rather than in the prompt, and that property is
   preserved here.

2. **Preference order** over whatever `tasks.supports()` derives. PySCF
   first because it needs no external binary or licence and starts
   instantly; ORCA next as the broadest and fastest of the two external
   engines; BAGEL last -- not because it is worse, but because on this host
   it is the slowest to start and the least widely applicable. A long
   BAGEL run is expected behaviour, never a reason to steer a user away
   from it (see CLAUDE.md); this ordering only decides what to pick when
   the user expressed no opinion at all.

An explicitly requested engine is never overridden. If it cannot run the
job the caller gets the derived refusal with its reasons, not a silent
substitution -- the user asked for something specific and deserves to be
told it is unavailable rather than quietly given something else.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.chemistry.registry2.capabilities import canonical_engine
from app.chemistry.registry2.tasks import SupportVerdict, engines_supporting, supports

# PySCF first, BAGEL last. Only consulted when no hard rule fired and the
# user named no engine.
ENGINE_PREFERENCE = ("pyscf", "orca", "bagel")


@dataclass(frozen=True)
class RoutingDecision:
    engine: Optional[str]
    # Why this engine and not another, in one sentence, for the approval
    # card and the agent's own explanation to the user.
    reason: str = ""
    warnings: tuple[str, ...] = ()
    # Populated only when engine is None.
    refusals: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.engine is not None


def _hard_rule(method: Optional[str], params: dict) -> Optional[tuple[str, str]]:
    """(engine, reason) when a mechanical rule decides the engine outright."""
    if method == "caspt2":
        return ("bagel", "BAGEL is the only engine in this deployment that implements "
                         "CASPT2 -- ORCA offers NEVPT2 instead, and PySCF has none here.")
    if method == "casscf" and params.get("want_oscillator_strengths"):
        return ("orca", "ORCA is the only engine here that computes CASSCF oscillator "
                        "strengths; the others would report energies with no intensities.")
    return None


def route_engine(
    method: Optional[str],
    task: str,
    subtype: str = "",
    requested_engine: Optional[str] = None,
    params: Optional[dict] = None,
) -> RoutingDecision:
    """Pick the engine for one job draft.

    Returns a `RoutingDecision` rather than raising, because every caller
    here -- the elicitation loop, the capability lookup tool, the registry
    API -- wants to *explain* an unavailable combination to the user rather
    than surface a traceback.
    """
    params = params or {}
    candidates = engines_supporting(method, task, subtype)

    # Canonicalised here as well as inside supports(), because the decision
    # this function returns carries the engine name onward to the job spec
    # and the approval card -- both of which are keyed on the lower-case form.
    requested_engine = canonical_engine(requested_engine)
    if requested_engine:
        verdict = supports(requested_engine, method, task, subtype)
        if verdict.supported:
            return RoutingDecision(
                engine=requested_engine,
                reason=f"{requested_engine.upper()} was requested explicitly.",
                warnings=verdict.warnings,
            )
        return RoutingDecision(
            engine=None,
            reason=f"{requested_engine.upper()} cannot run this job.",
            refusals=verdict.reasons,
            alternatives=candidates,
        )

    rule = _hard_rule(method, params)
    if rule is not None:
        engine, reason = rule
        verdict = supports(engine, method, task, subtype)
        if verdict.supported:
            return RoutingDecision(engine=engine, reason=reason, warnings=verdict.warnings)
        # The rule named an engine that cannot run this particular task
        # (e.g. a CASPT2 task BAGEL has no capability for). Fall through to
        # preference order rather than returning an engine that will fail
        # at submission -- but keep the rule's reasoning in the refusal so
        # the eventual message explains itself.
        if not candidates:
            return RoutingDecision(
                engine=None,
                reason=reason,
                refusals=verdict.reasons,
            )

    for engine in ENGINE_PREFERENCE:
        if engine not in candidates:
            continue
        verdict = supports(engine, method, task, subtype)
        others = [e for e in candidates if e != engine]
        reason = f"{engine.upper()} is the preferred engine for this combination"
        reason += (f"; {', '.join(e.upper() for e in others)} could also run it."
                   if others else " and the only one here that can run it.")
        return RoutingDecision(engine=engine, reason=reason, warnings=verdict.warnings)

    # Nothing can run it. Collect every engine's refusal so the user is told
    # why, not merely that.
    refusals: list[str] = []
    for engine in ENGINE_PREFERENCE:
        refusals.extend(supports(engine, method, task, subtype).reasons)
    label = f"{method} " if method else ""
    name = f"{task}/{subtype}" if subtype else task
    return RoutingDecision(
        engine=None,
        reason=f"No engine in this deployment can run a {label}{name} job.",
        refusals=tuple(dict.fromkeys(refusals)),
    )


def verdict_for(engine: str, method: Optional[str], task: str, subtype: str = "") -> SupportVerdict:
    """Thin re-export so callers importing routing don't also have to import
    tasks for the single-engine question."""
    return supports(engine, method, task, subtype)
