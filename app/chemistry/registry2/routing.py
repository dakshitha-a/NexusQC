"""Which engine runs a job when the user did not name one.

Two layers, in this order:

1. **Hard rules** -- routing decisions that are properties of this
   deployment rather than of a preference. CASPT2 exists on exactly one
   engine here, so that is not a choice to be made by preference order or
   by the model inferring intent. It is mechanical, which is the point.

   The second rule, `casscf + want_oscillator_strengths`, is a preference
   rather than a fact, and its history is worth keeping. It used to send
   those jobs to ORCA on the grounds that ORCA was "the only engine that
   computes them". That was wrong -- BAGEL computes them too, and the
   reason no BAGEL job ever produced any is that its runner never asked
   (fixed 2026-08-31). The rule was removed once the claim was known to
   be false, then reinstated pointing at BAGEL because the maintainer
   chose BAGEL for this combination. Same shape, opposite engine, and a
   reason that now says "preferred" instead of "only".

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

from app.chemistry.registry2.capabilities import canonical_engine, get_caps
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
    """(engine, reason) when a rule decides the engine outright.

    Two rules, and they are different KINDS of rule, which the reasons they
    return have to be honest about. The CASPT2 one is a fact: no other engine
    here implements it. The CASSCF one is a choice: ORCA and BAGEL can both
    produce those intensities, and the maintainer picked BAGEL. A reason that
    dressed the second up as the first is exactly the error this module
    carried for months -- it used to route CASSCF intensities to ORCA while
    asserting ORCA was the only engine that could compute them, which was not
    true and stopped anyone questioning the routing.
    """
    if method == "caspt2":
        return ("bagel", "BAGEL is the only engine in this deployment that implements "
                         "CASPT2 -- ORCA offers NEVPT2 instead, and PySCF has none here.")
    if method == "casscf" and params.get("want_oscillator_strengths"):
        return ("bagel", "BAGEL is this deployment's preferred engine for CASSCF "
                         "oscillator strengths. ORCA can also compute them and remains "
                         "available if you ask for it by name; PySCF cannot.")
    return None


def _requires_osc_strengths(method: Optional[str], params: dict) -> bool:
    """Whether this draft cannot be served by an engine with no intensities.

    `want_oscillator_strengths` is a parameter, not part of the task, so
    `supports()` does not consider it: a plain excited-state CASSCF job is
    supported on all three engines here, and only two of them can report an
    intensity. Preference order alone would therefore hand the job to PySCF
    and return energies with nothing beside them.

    This used to be expressed as a hard rule naming ORCA, on the grounds that
    ORCA was the only engine that computed CASSCF oscillator strengths. That
    was wrong about BAGEL, which gets transition dipoles from a forces block
    with `dipole` set and has carried `osc_strengths=True` in the capability
    table all along -- what was missing was the request, in
    `bagel_runner._build_input`. So the constraint is expressed as what it
    actually is, a filter on candidates, and which of the surviving engines
    wins is left to the ordinary preference order.
    """
    return bool(method) and bool(params.get("want_oscillator_strengths"))


def _requires_excited_gradient(task: str, subtype: str, params: dict) -> bool:
    """Whether this draft needs a gradient on a surface other than the
    ground state.

    Exactly the same shape of problem `_requires_osc_strengths` above
    solves, and it bit in exactly the same way. `single_point/grad`
    requires only the `gradient` capability, so every engine with a
    gradient is a candidate and preference order hands the job to PySCF --
    which has no CASSCF excited-state gradient at all. A batch asking for
    S0, S1 and S2 gradients therefore routed to PySCF and came back with
    thirteen ground-state gradients and nothing said about the rest.

    `target_states` is 1-based including the ground state, so only an entry
    above 1 means an excited surface; `[1]` is an ordinary ground-state
    request and must not narrow the candidate list.
    """
    if (task, subtype) != ("single_point", "grad"):
        return False
    return any(isinstance(s, int) and not isinstance(s, bool) and s > 1
               for s in (params.get("target_states") or []))


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

    # Drop engines that can run the task but cannot report the intensities
    # this draft asked for. Done before the preference walk rather than as a
    # hard rule naming one engine, so adding a third engine that can do it
    # needs no change here. If it would empty the list the filter is not
    # applied: an explicit refusal naming every engine is more useful than a
    # silent "nothing can run this".
    if _requires_osc_strengths(method, params):
        with_intensities = tuple(
            e for e in candidates
            if get_caps(e, method) is not None and get_caps(e, method).has("osc_strengths")
        )
        if with_intensities:
            candidates = with_intensities

    # Same filter, for the same reason, on excited-state gradients.
    if _requires_excited_gradient(task, subtype, params):
        with_es_gradient = tuple(
            e for e in candidates
            if get_caps(e, method) is not None and get_caps(e, method).has("excited_gradient")
        )
        if with_es_gradient:
            candidates = with_es_gradient

    # Canonicalised here as well as inside supports(), because the decision
    # this function returns carries the engine name onward to the job spec
    # and the approval card -- both of which are keyed on the lower-case form.
    requested_engine = canonical_engine(requested_engine)
    if requested_engine:
        verdict = supports(requested_engine, method, task, subtype)
        # `supports()` answers for the TASK, and single_point/grad requires
        # only `gradient` -- so an explicitly requested engine with no
        # excited-state gradient passes it and the draft reaches READY,
        # with the refusal arriving later at spec-build time. Checked here
        # instead so the user is told while they can still change the
        # engine, and told what to change it to.
        if verdict.supported and _requires_excited_gradient(task, subtype, params):
            caps = get_caps(requested_engine, method)
            if caps is None or not caps.has("excited_gradient"):
                return RoutingDecision(
                    engine=None,
                    reason=f"{requested_engine.upper()} cannot run this job.",
                    refusals=(
                        f"{requested_engine.upper()} has no excited-state gradient for "
                        f"method='{method}' in this app, and this job asks for one.",
                    ),
                    alternatives=candidates,
                )
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
