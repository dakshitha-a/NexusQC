"""Converts LangChain message objects and graph state into plain
JSON-serializable dicts for API responses/SSE payloads."""
from __future__ import annotations

from typing import Any


def serialize_message(m: Any) -> dict:
    return {
        "id": getattr(m, "id", None),
        "type": type(m).__name__,  # HumanMessage | AIMessage | ToolMessage | SystemMessage
        "content": m.content if isinstance(m.content, str) else str(m.content),
        "name": getattr(m, "name", None),
        "tool_call_id": getattr(m, "tool_call_id", None),
        "tool_calls": getattr(m, "tool_calls", None) or [],
    }


def serialize_state(state: dict) -> dict:
    return {
        "messages": [serialize_message(m) for m in state.get("messages", [])],
        "molecule": state.get("molecule"),
        "molecule_frames": state.get("molecule_frames", []),
        "active_job_ids": state.get("active_job_ids", []),
        "dynamic_tool_artifacts": state.get("dynamic_tool_artifacts", []),
    }
