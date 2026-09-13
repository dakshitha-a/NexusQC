"""Agent-facing academic-literature search tool (Semantic Scholar Graph
API), for open-ended questions about which method/active-space/basis-set
choices suit a molecular system -- grounded in the primary literature
rather than the agent's own (possibly stale or wrong) chemistry knowledge.
Unlike search_knowledge_base, this hits a public network service and only
covers published papers, not the software manuals -- use
search_knowledge_base(doc_type='paper') first for this category of
question (see SYSTEM_PROMPT), and fall back here when the local knowledge
base doesn't have relevant papers uploaded.

Uses /paper/search/bulk rather than /paper/search: the latter is
relevance-ranked but has no server-side sort and was observed returning
429 Too Many Requests repeatedly on the shared unauthenticated pool during
development, whereas bulk fared better and is the only endpoint that
supports sort=citationCount:desc ("seminal") / sort=publicationDate:desc
("latest"). Bulk's query syntax is literal boolean AND/OR of bare/quoted
tokens, not semantic search -- see this tool's own docstring for the
query-construction contract this requires.
"""
from __future__ import annotations

import requests
from langchain_core.tools import tool

from app.config import SEMANTIC_SCHOLAR_API_KEY, SEMANTIC_SCHOLAR_TIMEOUT

_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_FIELDS = "title,year,publicationDate,citationCount,venue,authors,abstract,url"
_MAX_SNIPPET_CHARS = 400
_SORT_BY_MODE = {"seminal": "citationCount:desc", "latest": "publicationDate:desc"}


@tool
def search_academic_literature(query: str, mode: str = "seminal", max_results: int = 5) -> str:
    """Search published scientific papers via the Semantic Scholar Graph
    API. Use this for questions about which method/active space/basis set/
    functional suits a molecular system, background on a new system, or
    finding foundational/recent literature -- AFTER checking
    search_knowledge_base(doc_type='paper') first, since papers the user
    already uploaded are a faster and more relevant source when they
    cover the topic.

    mode='seminal' (default) sorts by citation count, for foundational/
    highly-cited papers on a topic. mode='latest' sorts by publication
    date, for recent work. There is no relevance-ranked mode -- this
    endpoint does literal keyword matching, not semantic search.

    query MUST be a short set of distinctive technical keyword terms, NOT
    a full sentence, and multi-word technical terms MUST be double-quoted
    for exact-phrase matching -- confirmed empirically that bare common
    words (e.g. unquoted "active", "space") match unrelated papers by
    loose word overlap, and that a full natural-language sentence
    (6+ words) typically over-constrains to zero results since every term
    is ANDed together.
      GOOD: query='"active space" CASSCF retinal photoisomerization'
      GOOD: query='"basis set" diffuse functions anion'
      BAD:  query='what active space should I use for CASSCF calculations
            of retinal photoisomerization excited states' (too many bare
            terms, likely zero results)
      BAD:  query='active space' (unquoted common words, noisy/irrelevant
            results)

    Returns title, year, venue, citation count, and a truncated abstract
    for the top results. If this returns no results, try fewer/broader
    quoted terms before giving up, or fall back to web_search. If this
    tool errors (including a rate-limit response), it tells you to use
    web_search instead of retrying this tool -- do not retry
    search_academic_literature after that message.
    """
    max_results = max(1, min(max_results, 8))
    sort = _SORT_BY_MODE.get(mode, _SORT_BY_MODE["seminal"])
    headers = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
    params = {"query": query, "fields": _FIELDS, "sort": sort, "limit": max_results}
    try:
        resp = requests.get(_SEARCH_URL, params=params, headers=headers, timeout=SEMANTIC_SCHOLAR_TIMEOUT)
    except Exception as e:
        return f"Academic literature search failed ({e}). Use web_search instead -- do not retry this tool."
    if resp.status_code == 429:
        return (
            "Academic literature search is rate-limited right now (Semantic Scholar's shared "
            "unauthenticated quota). Use web_search instead -- do not retry this tool for this turn."
        )
    if not resp.ok:
        return f"Academic literature search failed (HTTP {resp.status_code}). Use web_search instead."
    # Inside a guard, because a 200 is not a promise of JSON. R-086: the try
    # above was scoped to the connection rather than to the round trip, so a
    # proxy interstitial or an HTML error page served with a 200 raised
    # JSONDecodeError straight out of the tool. ToolNode catches that into a
    # ToolMessage, so it was never a crashed turn -- but this function's own
    # docstring promises that any error, rate limits included, comes back as
    # "use web_search instead", and a raw traceback is not that.
    try:
        data = resp.json().get("data") or []
    except Exception as e:                                      # noqa: BLE001
        return (f"Academic literature search returned something that is not JSON ({e}). "
                f"Use web_search instead -- do not retry this tool.")
    if not data:
        return (
            "No matching papers found. Try fewer/broader quoted terms (this endpoint does literal "
            "keyword matching, not semantic search), or fall back to web_search."
        )
    blocks = []
    for p in data:
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
        abstract = (p.get("abstract") or "")[:_MAX_SNIPPET_CHARS]
        blocks.append(
            f"{p.get('title', '')} ({p.get('year', '?')}, {p.get('venue', '')})\n"
            f"Authors: {authors}\nCitations: {p.get('citationCount', '?')}\n"
            f"URL: {p.get('url', '')}\n{abstract}"
        )
    return "\n\n---\n\n".join(blocks)
