"""Agent-facing RAG tool: semantic search over uploaded manuals/papers."""
from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app.agent.state import AgentState
from app.rag.store import SHARED_OWNER, get_store


@tool
def search_knowledge_base(
    query: str, doc_type: str = "any", k: int = 5,
    state: Annotated[Optional[AgentState], InjectedState] = None,
) -> str:
    """Search the knowledge base of quantum chemistry software manuals and
    scientific papers the user has uploaded. Use this when you need
    accurate, citable details for preparing correct inputs (e.g. exact
    ORCA/BAGEL keyword syntax, valid basis set names, method-specific
    caveats) or chemical background on a molecular system the user is
    working on, rather than relying on general knowledge.

    Set doc_type explicitly rather than leaving it 'any': use
    doc_type='manual' for software syntax/keyword/input-preparation
    questions, and doc_type='paper' for conceptual questions -- method/
    active-space/basis-set recommendations, background on a molecular
    system, or "what does the literature say about X" -- since mixing the
    two risks surfacing a software manual snippet for a chemistry-judgment
    question or vice versa. For the conceptual/paper category, this should
    be your FIRST source (papers the user already uploaded), before
    search_academic_literature (Semantic Scholar) or web_search. Returns
    the top-k matching passages with their source filename; if it comes
    back empty, say so and move to the next source in the hierarchy rather
    than guessing.
    """
    store = get_store()
    owner = (state or {}).get("owner_user_id")
    # owner is only absent when auth isn't configured for this deployment
    # (see AgentState.owner_user_id's docstring) -- in that single-user
    # case there's no one else's private content to scope away from, so
    # this falls through to an unfiltered search, exactly like every KB
    # search before the ownership retrofit. Once a real owner exists,
    # every query is scoped to shared content plus that user's own uploads
    # -- this is the one retrieval path (unlike the manuals-only
    # _kb_context_for_job in app/agent/tools.py) that explicitly supports
    # doc_type='paper', the more privacy-sensitive case: an uploaded paper
    # could be a genuinely private/proprietary document, and without this
    # scoping any user's chat could trigger a search that surfaces another
    # user's private upload verbatim into the model's context.
    where: dict = {"doc_type": doc_type} if doc_type != "any" else {}
    if owner:
        owner_clause = {"$or": [{"owner": SHARED_OWNER}, {"owner": owner}]}
        where = {"$and": [where, owner_clause]} if where else owner_clause
    results = store.similarity_search(query, k=k, filter=where or None)
    if not results:
        return "No matching passages found in the knowledge base (it may be empty -- ask the user to upload manuals/papers)."

    blocks = []
    for doc in results:
        src = doc.metadata.get("source", "unknown")
        blocks.append(f"[{src}]\n{doc.page_content}")
    return "\n\n---\n\n".join(blocks)
