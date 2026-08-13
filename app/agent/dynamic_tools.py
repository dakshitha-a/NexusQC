"""User-approved, LLM-authored tools created at runtime via `create_tool`
(see `tools.py`) for tasks with no pre-built tool -- new output parsers,
custom plots, or QM-calculation helpers.

Every dynamic tool is a single Python module on disk defining exactly one
function, `def run(params: dict) -> dict:`. That fixed convention is what
makes the rest of this module tractable: the wrapper LangChain tool built
around it always has the same signature, so there's no need to safely
introspect or execute untrusted code just to build its calling schema.

Persistence lives in `DYNAMIC_TOOLS_DIR` (`data/dynamic_tools/`, like
`data/jobs`/`data/kb`) as a `<name>.py` (the approved source) + `<name>.json`
(description, param_description, created_at) pair per tool, so tools
survive a process restart -- `load_dynamic_tools()` re-scans the directory
on every call rather than caching, so a tool approved in one conversation
is picked up by the very next graph rebuild in any other.

Execution is subprocess-isolated via `dynamic_tool_worker.py`, the same
shape as the QC job workers in `app/chemistry/jobs/` -- a crash in a
dynamic tool can't take down the agent process. This is process isolation
for crash containment, matching the trust model already established for
job workers, not a security sandbox: the subprocess has the same
filesystem/network permissions as the rest of the app. `validate_tool_code`
below and the mandatory human-approval step (`create_tool`'s `interrupt()`)
are the actual safety gates -- the static AST checks here are a defense-in-
depth backstop against obviously-wrong-not-just-unreviewed code, not a
guarantee the code is safe to run unread.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.config import DYNAMIC_TOOLS_DIR, PROJECT_ROOT

# Root package names a dynamic tool's `import`/`from ... import` statements
# may reference (checked at any nesting depth, not just module level).
# Deliberately excludes subprocess/socket/shutil/sys/ctypes/importlib/
# requests/urllib/pickle -- none of those are needed for "parser, plot, or
# QM-calculation helper" and each is a classic way to reach outside that
# scope (spawn processes, hit the network, delete files in bulk).
_ALLOWED_MODULES = {
    "re", "json", "math", "statistics", "itertools", "collections", "functools",
    "dataclasses", "typing", "datetime", "numpy", "scipy", "matplotlib", "pyscf", "rdkit",
}
# os.path (path joining/existence checks) is allowed without the rest of os.
_ALLOWED_OS_SUBMODULES = {"os.path"}

_BANNED_CALL_NAMES = {"eval", "exec", "compile", "__import__", "globals", "locals"}

RESERVED_TOOL_NAMES = {
    "set_molecule", "generate_job_input", "submit_job", "check_job_status",
    "plot_excited_state_spectrum", "search_knowledge_base", "create_tool",
}


def _root_module(name: str) -> str:
    return name.split(".")[0]


def validate_tool_code(code: str) -> list[str]:
    """Structural + import/call safety checks. Returns a list of human-
    readable problems; empty means the code passed these checks (NOT that
    it's safe or correct -- see module docstring)."""
    errors: list[str] = []
    if not code.strip():
        return ["Code is empty."]

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error: {e}"]

    run_defs = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    ]
    if len(run_defs) != 1:
        errors.append("Code must define exactly one top-level function named 'run'.")
    else:
        run_fn = run_defs[0]
        arg_names = [a.arg for a in run_fn.args.args]
        if arg_names != ["params"]:
            errors.append("'run' must take exactly one parameter named 'params' (def run(params: dict) -> dict:).")

    allowed_top_level = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring
        if not isinstance(node, allowed_top_level):
            errors.append(
                f"Line {node.lineno}: top-level statements are limited to imports, constants, and function/class "
                f"definitions -- no executable code should run at import time (found {type(node).__name__})."
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root_module(alias.name)
                if root == "os" and alias.name not in _ALLOWED_OS_SUBMODULES:
                    errors.append(f"Line {node.lineno}: 'import {alias.name}' is not allowed (only 'os.path' is).")
                elif root != "os" and root not in _ALLOWED_MODULES:
                    errors.append(f"Line {node.lineno}: 'import {alias.name}' is not on the allowed module list.")
        elif isinstance(node, ast.ImportFrom):
            root = _root_module(node.module or "")
            if root == "os" and node.module not in _ALLOWED_OS_SUBMODULES:
                errors.append(f"Line {node.lineno}: 'from {node.module} import ...' is not allowed (only 'os.path' is).")
            elif root != "os" and root not in _ALLOWED_MODULES:
                errors.append(f"Line {node.lineno}: 'from {node.module} import ...' is not on the allowed module list.")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _BANNED_CALL_NAMES:
            errors.append(f"Line {node.lineno}: use of '{node.func.id}(...)' is not allowed.")

    return errors


def _tool_paths(name: str) -> tuple[Path, Path]:
    return DYNAMIC_TOOLS_DIR / f"{name}.py", DYNAMIC_TOOLS_DIR / f"{name}.json"


def is_valid_tool_name(name: str) -> bool:
    return name.isidentifier() and not name.startswith("_")


def tool_exists(name: str) -> bool:
    py_path, _ = _tool_paths(name)
    return py_path.exists()


def save_tool(name: str, description: str, code: str, param_description: str) -> None:
    py_path, meta_path = _tool_paths(name)
    py_path.write_text(code)
    meta_path.write_text(json.dumps({
        "name": name, "description": description, "param_description": param_description,
        "created_at": time.time(),
    }, indent=2))


def delete_tool(name: str) -> None:
    py_path, meta_path = _tool_paths(name)
    py_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)


def list_tools() -> list[dict]:
    tools = []
    for meta_path in sorted(DYNAMIC_TOOLS_DIR.glob("*.json")):
        try:
            tools.append(json.loads(meta_path.read_text()))
        except json.JSONDecodeError:
            continue
    return tools


def _run_in_subprocess(name: str, params: dict) -> dict:
    py_path, _ = _tool_paths(name)
    if not py_path.exists():
        return {"error": f"Dynamic tool '{name}' is no longer registered (its file may have been removed)."}

    work_dir = DYNAMIC_TOOLS_DIR / "_runs" / f"{name}_{int(time.time() * 1000)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    params_path = work_dir / "params.json"
    result_path = work_dir / "result.json"
    params_path.write_text(json.dumps(params))

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.agent.dynamic_tool_worker", name, str(params_path), str(result_path)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=6 * 3600,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"Dynamic tool '{name}' timed out after 6 hours."}

    if result_path.exists():
        try:
            return json.loads(result_path.read_text())
        except json.JSONDecodeError:
            pass
    tail = (proc.stdout or "") + (proc.stderr or "")
    return {"error": f"Dynamic tool '{name}' produced no result (exit code {proc.returncode}).\n{tail[-2000:]}"}


def _make_tool(meta: dict) -> StructuredTool:
    name = meta["name"]

    def _invoke(
        params: dict,
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None,
    ) -> Command:
        result = _run_in_subprocess(name, params)
        if "error" in result:
            content = f"Dynamic tool '{name}' failed: {result['error']}"
            return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})

        extra_update = {}
        image_path = result.get("image_path")
        if image_path and Path(image_path).exists():
            extra_update["dynamic_tool_artifacts"] = [image_path]

        text = result.get("text") or json.dumps({k: v for k, v in result.items() if k != "image_path"})
        if image_path:
            text += f"\n\n(An image was generated and is now shown to the user: {image_path})"
        return Command(update={**extra_update, "messages": [ToolMessage(content=text, tool_call_id=tool_call_id)]})

    description = meta["description"]
    if meta.get("param_description"):
        description += f"\n\nExpected params dict: {meta['param_description']}"

    return StructuredTool.from_function(func=_invoke, name=name, description=description)


def load_dynamic_tools() -> list[StructuredTool]:
    return [_make_tool(meta) for meta in list_tools() if is_valid_tool_name(meta.get("name", ""))]
