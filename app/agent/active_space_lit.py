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

from dataclasses import dataclass, field
from typing import Callable, Optional

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


def _is_empty(text: Optional[str]) -> bool:
    if not text or not text.strip():
        return True
    return any(text.lstrip().startswith(m) for m in _NO_RESULT_MARKERS)


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

    def as_notes(self) -> str:
        """The text that rides into the job's `literature_notes`, and that
        the final report is reconciled against.

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
                f"matched on the molecule, {self.n_states} state-averaged root(s) and the "
                f"{self.basis} basis"),
            "molecule+states": (
                f"matched on the molecule and {self.n_states} state-averaged root(s); the "
                f"{self.basis} basis did not narrow it further, so basis-specific details "
                f"may differ" if self.basis else
                f"matched on the molecule and {self.n_states} state-averaged root(s)"),
            "molecule": (
                "matched on the molecule alone -- neither the state count nor the basis "
                "narrowed it, so any active space below was chosen under conditions that "
                "may not be the ones being asked for here"),
        }[self.matched_at]
        blocks = "\n\n---\n\n".join(f"[{src}]\n{text}" for src, text in self.hits)
        return (
            f"Literature search for an active space for {self.molecule}, {qualifier}.\n\n"
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
                      f'"{molecule}" "active space" CASSCF "{basis}" {n_states} states'))
    if n_states:
        tiers.append(("molecule+states",
                      f'"{molecule}" "active space" CASSCF state-averaged {n_states} states'))
    tiers.append(("molecule", f'"{molecule}" "active space" CASSCF'))
    return tiers


def search(
    molecule: str,
    n_states: Optional[int] = None,
    basis: Optional[str] = None,
    *,
    kb: Optional[Callable[[str], str]] = None,
    scholar: Optional[Callable[[str], str]] = None,
    web: Optional[Callable[[str], str]] = None,
) -> LiteratureFindings:
    """Run the staged search and return what it found.

    The three backends are parameters rather than imports so a test can
    drive the staging logic -- which tier matched, what relaxed, what the
    no-match outcome says -- without a network call or a seeded knowledge
    base. Production callers pass none of them and get the real three, in
    the hierarchy the tools' own docstrings already establish: the user's
    uploaded papers first, then Semantic Scholar, then the open web.
    """
    if kb is None or scholar is None or web is None:
        from app.agent.scholar_search import search_academic_literature
        from app.agent.web_search import web_search
        from app.rag.query_tool import search_knowledge_base

        kb = kb or (lambda q: search_knowledge_base.func(q, doc_type="paper", k=5, state=None))
        scholar = scholar or (lambda q: search_academic_literature.func(q, max_results=5))
        web = web or (lambda q: web_search.func(q, max_results=5))

    findings = LiteratureFindings(molecule=molecule, matched_at="none",
                                  n_states=n_states, basis=basis)
    scholar_disabled = False
    for label, query in _tiers(molecule, n_states, basis):
        findings.queries_tried.append(query)
        hits: list[tuple[str, str]] = []
        for source, fn in (("knowledge base", kb), ("published literature", scholar),
                           ("web", web)):
            if source == "published literature" and scholar_disabled:
                continue
            try:
                text = fn(query)
            except Exception as exc:  # noqa: BLE001 -- a dead backend must not
                # sink the whole search; the other two may still answer, and a
                # tier that found nothing because a backend threw is reported
                # as "nothing", which is honest.
                text = f"{source} search failed ({exc})."
            if source == "published literature" and text and "rate-limited" in text:
                # Its own docstring says not to retry after this, and that
                # applies across tiers, not just within one.
                scholar_disabled = True
            if not _is_empty(text):
                hits.append((source, text))
        if hits:
            findings.matched_at = label
            findings.hits = hits
            return findings
    return findings
