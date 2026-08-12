"""Subprocess entry point for a user-approved dynamic tool:
`python -m app.agent.dynamic_tool_worker <tool_name> <params.json> <result.json>`

Mirrors the QC job workers in `app/chemistry/jobs/`: runs in its own
process so a crash or hang in dynamically-authored code can't take down
the agent, and writes its result to disk rather than to stdout so the
caller doesn't have to parse mixed program output.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback

from app.config import DYNAMIC_TOOLS_DIR


def main(tool_name: str, params_path: str, result_path: str) -> None:
    params = json.loads(open(params_path).read())
    module_path = DYNAMIC_TOOLS_DIR / f"{tool_name}.py"

    try:
        spec = importlib.util.spec_from_file_location(f"dynamic_tool_{tool_name}", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.run(params)
        if not isinstance(result, dict):
            result = {"text": str(result)}
    except Exception:
        result = {"error": traceback.format_exc()}

    with open(result_path, "w") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
