"""Agent-facing RAG tool: semantic search over uploaded manuals/papers."""
from __future__ import annotations

from langchain_core.tools import tool

from app.rag.store import get_store


@tool
def search_knowledge_base(query: str, doc_type: str = "any", k: int = 5) -> str:
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
    filter_ = None if doc_type == "any" else {"doc_type": doc_type}
    results = store.similarity_search(query, k=k, filter=filter_)
    if not results:
        return "No matching passages found in the knowledge base (it may be empty -- ask the user to upload manuals/papers)."

    blocks = []
    for doc in results:
        src = doc.metadata.get("source", "unknown")
        blocks.append(f"[{src}]\n{doc.page_content}")
    return "\n\n---\n\n".join(blocks)
