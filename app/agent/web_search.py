"""Agent-facing web search tool (DuckDuckGo, via the `ddgs` package) --
for troubleshooting help the local knowledge base doesn't cover, e.g. a
specific engine error message or a basis-set naming quirk not documented
in the seeded manuals. Unlike search_knowledge_base, this hits a public
network service, so the system prompt tells the agent to prefer local
sources first and use this only when they're insufficient.
"""
from __future__ import annotations

from ddgs import DDGS
from langchain_core.tools import tool

from app.config import WEB_SEARCH_TIMEOUT

_MAX_SNIPPET_CHARS = 300


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web via DuckDuckGo. Use this when
    search_knowledge_base doesn't have enough information -- most
    commonly, troubleshooting a failed job's exact error message or an
    engine-specific syntax quirk the seeded manuals don't cover. Returns
    titles, URLs, and short snippets for the top results; treat the
    snippets as evidence, don't assume a URL's full content based on its
    title alone. Prefer search_knowledge_base and your own knowledge
    first -- this is a network call to a public search engine, not a
    first resort.
    """
    max_results = max(1, min(max_results, 8))
    try:
        results = DDGS(timeout=WEB_SEARCH_TIMEOUT).text(query, max_results=max_results)
    except Exception as e:
        return f"Web search failed ({e}). Fall back to search_knowledge_base or your own knowledge."
    if not results:
        return "No web results found for that query."
    blocks = []
    for r in results:
        title = r.get("title", "")
        url = r.get("href", "")
        body = (r.get("body") or "")[:_MAX_SNIPPET_CHARS]
        blocks.append(f"{title}\n{url}\n{body}")
    return "\n\n---\n\n".join(blocks)
