"""Literature search for an active-space question, with a match hierarchy
that never leaves the molecule.

Why this exists as its own module rather than as prose in a prompt. Asked
to recommend an active space for cis,cis-1,3-cyclooctadiene, the agent ran
three ad-hoc searches, found exactly one active space anywhere in the
results -- a (6e,6o) `1pi + 1pi* + 2sigma + 2sigma*` space for
**cyclotetrasilene**, a different molecule from a different paper -- copied
its shape, doubled the pi part to reach (8e,8o), and attributed the
reasoning to a cyclooctadiene surface-hopping paper that gave no active
space at all. It then argued specifically against (4e,4o), which is what
this app's own pipeline recommended forty messages later.

Nothing in that sequence was a retrieval failure. The searches worked; the
`literature_notes` field they were meant to fill was a passthrough nothing
populated, so the model filled it by hand, and a model with an empty field
and a nearby number will scale the number. The fix is to make the search a
real step with a real "nothing found" outcome, so that outcome is
reportable instead of being the one result the model cannot return.

The hierarchy, in the order the user specified: molecule, then the number
of state-averaged roots, then the basis set. Terms relax off the end --
basis first, then state count -- and the molecule never relaxes at all. A
result for a different system is not a weaker match, it is not a match, and
the whole point of the staging is that "no published active space for this
molecule" is a first-class answer.
"""
from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Every no-result and every failure string the three search backends can
# return, matched as a prefix. Coupling to another module's prose is not
# free, so it is worth saying why it is the right trade here: the
# alternative is restructuring three tools that are already used directly
# by the model into returning structured data, which changes what the model
# sees in a hundred existing conversations to fix a problem in one new
# code path. These strings are literal constants in their own modules
# (rag/query_tool.py, agent/scholar_search.py, agent/web_search.py); a
# change to one shows up here as a tier that never matches, which the
# `queries_tried` field on the findings makes visible rather than silent.
_NO_RESULT_MARKERS = (
    "No matching passages found",
    "No matching papers found",
    "No web results found",
    "Academic literature search failed",
    "Academic literature search is rate-limited",
    "Web search failed",
)

# What `_call` returns when a backend RAISES. It is in its own constant, and
# _is_empty checks it, because R-015 was the two halves disagreeing: the
# markers above were written against the three tools' own "nothing found"
# strings, and _call invented a different sentence for an exception. Nothing
# recognised it, so a backend that threw was absorbed as a literature HIT --
# the recommendation then read as grounded in a paper, and `matched_at`
# named a tier, on the strength of a stack trace. The empty result is this
# feature's guardrail (the user settled that when they kept the literature
# step rather than dropping it), so an exception reading as a hit removes
# exactly the thing the step is for.
_BACKEND_FAILED_PREFIX = "BACKEND UNAVAILABLE:"


def _is_empty(text: Optional[str]) -> bool:
    if not text or not text.strip():
        return True
    stripped = text.lstrip()
    if stripped.startswith(_BACKEND_FAILED_PREFIX):
        return True
    return any(stripped.startswith(m) for m in _NO_RESULT_MARKERS)


@dataclass
class LiteratureFindings:
    """What the search found, and -- as importantly -- how far it had to
    relax to find it."""

    molecule: str
    #: "molecule+states+basis" | "molecule+states" | "molecule" | "none"
    matched_at: str
    queries_tried: list[str] = field(default_factory=list)
    hits: list[tuple[str, str]] = field(default_factory=list)  # (source, text)
    n_states: Optional[int] = None
    basis: Optional[str] = None

    @property
    def found(self) -> bool:
        return self.matched_at != "none"

    def as_job_note(self) -> str:
        """The short form that rides into the job's `literature_notes`.

        `as_notes` is written for the moment the model is about to propose a
        space, and its not-found branch spends most of its words telling it not
        to substitute a space from a similar molecule. That instruction has to
        be there. It does NOT have to be there three more times: the string was
        being copied into the job's parameters, stored in the finished job's
        summary, and read back out again at report time, where
        `job_watcher`'s own notice already says what to do with an empty
        result. So the empty case, which is the common one, was paying for the
        same seventy words at every stage of the chain.

        The found case is not shortened. Its content is the actual finding and
        is what the report is reconciled against.
        """
        if not self.found:
            n = len(self.queries_tried)
            return (f"No published active space found for {self.molecule} "
                    f"({n} quer{'y' if n == 1 else 'ies'} tried).")
        return self.as_notes()

    def as_notes(self) -> str:
        """The full text, shown to the model at search time, when it is about
        to propose a space and the guardrail has to be in front of it.

        Written to be read next to a computed active space, so it always
        states what was searched for and how closely the hits match it --
        a hit found only after dropping the basis and the state count is a
        weaker claim than one that matched all three, and the difference
        has to survive into the report rather than being flattened into
        "the literature says".
        """
        if not self.found:
            return (
                f"Literature search for an active space for {self.molecule}: nothing found. "
                f"Queries tried: {'; '.join(self.queries_tried)}. No published active space "
                f"for this molecule was located, which is the finding -- do not substitute "
                f"an active space reported for a different molecule, however similar. Any "
                f"space proposed from here is this app's own computed result or a judgement "
                f"stated as one, not a literature value."
            )
        qualifier = {
            "molecule+states+basis": (
                f"the narrowest query -- molecule, {self.n_states} state-averaged root(s) "
                f"and the {self.basis} basis -- returned results"),
            "molecule+states": (
                f"results came back only after dropping the {self.basis} basis from the "
                f"query, so basis-specific details may differ" if self.basis else
                f"the query on the molecule and {self.n_states} state-averaged root(s) "
                f"returned results"),
            "molecule": (
                "results came back only for the molecule alone -- neither the state count "
                "nor the basis narrowed the query, so anything below was chosen under "
                "conditions that may not be the ones being asked about here"),
        }[self.matched_at]
        blocks = "\n\n---\n\n".join(f"[{src}]\n{text}" for src, text in self.hits)
        # "Returned results", never "matched" -- all three backends do keyword
        # retrieval, so a query about an active space for water comes back
        # just as happily with an ORCA manual page on CASSCF syntax and a
        # paper about DNA base pairs. Observed on the first live run of this
        # flow, at the narrowest tier. Whether any of it is actually about
        # this molecule's active space is a judgement the retrieval layer
        # cannot make, so the text must not pre-empt it: claiming a match the
        # hits do not support is the same overstatement, one level up, that
        # this whole module exists to stop.
        return (
            f"Literature search for an active space for {self.molecule}: {qualifier}.\n\n"
            f"Read these before relying on them -- keyword search returns method "
            f"documentation and papers on other systems alongside anything genuinely "
            f"about {self.molecule}. If none of it reports an active space chosen for "
            f"this molecule, say so; that is the same finding as an empty search.\n\n"
            f"{blocks}"
        )


def _tiers(molecule: str, n_states: Optional[int], basis: Optional[str]):
    """(label, query) per tier, most specific first.

    The molecule is double-quoted in every one of them. Semantic Scholar
    does literal keyword matching and ANDs bare terms together (see
    scholar_search's docstring), so an unquoted multi-word molecule name
    both over-constrains and matches unrelated papers by word overlap --
    and the molecule is the one term that must never be the reason a query
    matches something else.
    """
    tiers = []
    if n_states and basis:
        tiers.append(("molecule+states+basis",
                      f'"{molecule}" "active space" CASSCF {basis} {n_states}-state'))
    if n_states:
        # "{n}-state state-averaged" rather than "{n} states": the former is
        # how papers actually write it ("a 3-state state-averaged CASSCF"),
        # and this is literal keyword matching, so the phrasing IS the query.
        tiers.append(("molecule+states",
                      f'"{molecule}" "active space" CASSCF {n_states}-state '
                      f'state-averaged'))
    tiers.append(("molecule", f'"{molecule}" "active space" CASSCF'))
    return tiers


def search(
    molecule: str,
    n_states: Optional[int] = None,
    basis: Optional[str] = None,
    *,
    state: Optional[dict] = None,
    kb: Optional[Callable[[str], str]] = None,
    scholar: Optional[Callable[[str], str]] = None,
    web: Optional[Callable[[str], str]] = None,
) -> LiteratureFindings:
    """Run the staged search and return what it found.

    The backends are parameters rather than imports so a test can drive the
    staging logic -- which tier matched, what relaxed, what the no-match
    outcome says -- without a network call or a seeded knowledge base.

    **`state` is not optional in production and the default kb backend is
    why.** The knowledge-base tier searches `doc_type="paper"`, which is the
    user's own uploaded literature, and `app/rag/query_tool.py` reads the
    owner to scope that search off exactly this dict. Passing `None` there
    made the search unscoped, so one user's active-space question retrieved
    another user's private paper verbatim into their conversation and into
    the resulting job's `literature_notes` (R-009). query_tool's own comment
    had already named the harm and called `doc_type="paper"` the more
    privacy-sensitive of the two cases.

    Both callers in `tools.py` already hold the agent state; the argument was
    simply never threaded through, because this signature was written for
    injectable test backends and the production default was written to fit
    it. It stays optional in the signature so a test can still call this with
    its own `kb`, and it is required whenever the default backend is built.

    **`web` is accepted and no longer called by default.** It was the third
    backend and it was the noise source, for the reason the tier comment below
    already recorded: it returns something for almost any string. That makes
    it the one backend whose hits carry the least information per token, and
    it was being asked three times per recommendation, once per tier. A caller
    that wants it can still pass one; production no longer builds one.
    """
    if kb is None:
        # Refused rather than defaulted to unscoped. An unscoped paper search
        # is a cross-user read (R-009), so "the caller forgot" must not be a
        # quieter path to it than "the caller asked for it".
        if state is None:
            raise ValueError(
                "active_space_lit.search needs the agent state to scope the "
                "knowledge-base tier to the caller's own uploaded papers. Pass "
                "state=..., or pass an explicit kb= backend in a test."
            )
    if kb is None or scholar is None:
        from app.agent.scholar_search import search_academic_literature
        from app.rag.query_tool import search_knowledge_base

        kb = kb or (lambda q: search_knowledge_base.func(q, doc_type="paper", k=5, state=state))
        scholar = scholar or (lambda q: search_academic_literature.func(q, max_results=5))

    findings = LiteratureFindings(molecule=molecule, matched_at="none",
                                  n_states=n_states, basis=basis)
    scholar_disabled = False
    seen: set[str] = set()
    # EVERY tier runs, and the results are merged -- the narrower tiers are a
    # preference ordering, not a stop condition.
    #
    # Stopping at the first tier that returned anything looked right and was
    # wrong in practice, because a web backend returns something for almost
    # any string. The narrowest query therefore satisfied the search every
    # single time, and the broader, more productive ones were never issued.
    # Caught on uracil, which unlike the earlier test molecules has real
    # published spaces: the narrow query gave a flaky mix of method
    # documentation and unrelated systems, while the molecule-only query
    # returned several uracil CASSCF papers including a CASSCF(10,9). The
    # user's hierarchy -- molecule, then state count, then basis -- is about
    # which hits to prefer, and running one query could never express that.
    # The local index runs first and alone, across every tier. It is the
    # user's own uploaded papers, it costs no network call, and it is the most
    # relevant source there is for "what space did WE use for this molecule".
    # If it answers at the narrowest tier -- molecule, state count and basis
    # all matched -- the network backend is not asked at all, which is the
    # whole of the saving in the common case where the paper is on file.
    #
    # This is a narrower short-circuit than the one the comment above rejects,
    # and the difference is which backend is trusted to mean something by
    # answering. A web hit at the narrow tier meant nothing, so stopping there
    # skipped the productive queries. A local hit at the narrow tier means a
    # paper the user uploaded matched all three terms.
    tiers = list(_tiers(molecule, n_states, basis))
    for label, query in tiers:
        findings.queries_tried.append(query)
        _absorb(findings, seen, "knowledge base", label, _call(kb, "knowledge base", query))

    if findings.matched_at == tiers[0][0]:
        return findings

    backends = [("published literature", scholar)]
    if web is not None:
        backends.append(("web", web))
    for label, query in tiers:
        for source, fn in backends:
            if source == "published literature" and scholar_disabled:
                continue
            text = _call(fn, source, query)
            if source == "published literature" and text and "rate-limited" in text:
                # Its own docstring says not to retry after this, and that
                # applies across tiers, not just within one.
                scholar_disabled = True
            _absorb(findings, seen, source, label, text)
    return findings


def _call(fn, source: str, query: str) -> str:
    """One backend call, where a dead backend does not sink the search.

    The others may still answer, and a search that found nothing because a
    backend threw is reported as "nothing", which is honest.
    """
    try:
        return fn(query)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("active-space literature: the %s backend raised: %s", source, exc)
        return f"{_BACKEND_FAILED_PREFIX} the {source} search raised ({exc})."


def _absorb(findings: "LiteratureFindings", seen: set, source: str,
            label: str, text: str) -> None:
    """Record one backend's answer, de-duplicated, and note the tier."""
    if _is_empty(text):
        return
    key = text.strip()[:200]
    if key in seen:
        return
    seen.add(key)
    findings.hits.append((f"{source}, {label}", text))
    if findings.matched_at == "none":
        # The first tier to answer is the most specific one that did, since
        # tiers run narrowest first.
        findings.matched_at = label
