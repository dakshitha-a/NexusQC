"""Dynamic agent-tool listing/removal. Creation goes through the chat
interrupt/approval flow (server/routes/chat.py's approve_tool), not a
dedicated endpoint here -- see app/agent/dynamic_tools.py's create_tool."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agent.dynamic_tools import delete_tool, list_tools, tool_exists
from app.agent.graph import invalidate_graph_cache

router = APIRouter()


@router.get("/api/tools")
def get_tools():
    return list_tools()


@router.delete("/api/tools/{name}")
def remove_tool(name: str):
    if not tool_exists(name):
        raise HTTPException(status_code=404, detail=f"No such tool: {name}")
    delete_tool(name)
    invalidate_graph_cache()
    return {"deleted": True}
