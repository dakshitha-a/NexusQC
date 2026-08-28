#!/usr/bin/env python3
"""No tool result tells the model to call a tool that does not exist.

    PYTHONPATH=$PWD python3 tests/backend/tools_01_no_dead_tool_names.py

The rebuild retired `set_molecule`, `set_pes_scan_endpoint` and
`generate_job_input`, and `submit_job` survives only as a non-advertised
shim for approval cards created by an older agent. Six model-facing strings
went on naming them anyway, so a user who hit one of those paths got an
agent confidently calling a tool that is not bound: `resolve_basis_from_bse`
ended its SUCCESS path by naming two of them, and three scan/NEB refusals
named two dead tools in a single sentence.

Nothing catches this by running the app, because a refusal string is only
reached on the paths that refuse, and the model's reaction to an impossible
instruction is to improvise rather than to error. So it is checked
structurally instead.

Deliberately scans string literals only, via the AST, rather than the file
text. Comments and docstrings legitimately mention retired tools when they
explain why something looks the way it does -- `_draft_input_preview`'s
docstring says outright that it replaced `generate_job_input` -- and a
text-level grep would either lose that history or have to carry an
allow-list of line numbers that rots on the next edit.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.agent.tools import STATIC_TOOLS  # noqa: E402

failures: list[str] = []
checks = 0

# Names a model could read as an instruction. `submit_job` is included even
# though the shim still exists, because it is deliberately not advertised
# (see get_executable_tools) and so cannot be called by the model.
RETIRED = ("set_molecule", "set_pes_scan_endpoint", "generate_job_input", "submit_job")

SCANNED = [
    REPO / "app" / "agent" / "tools.py",
    REPO / "app" / "chemistry" / "jobs" / "dispatch.py",
    REPO / "app" / "agent" / "prompts.py",
]


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def string_literals(path: Path):
    """Every string constant in the module that is not a docstring.

    Docstrings are excluded by collecting the ones ast marks as such and
    skipping those node objects; everything else that survives is a literal
    the code actually returns, formats or embeds.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def main() -> int:
    bound = {t.name for t in STATIC_TOOLS}
    print("\n== the retired names are genuinely gone ==")
    for name in RETIRED:
        check(f"{name} is not a bound tool", name not in bound, "it is still bound")

    print("\n== and nothing tells the model to call one ==")
    for path in SCANNED:
        offenders = []
        for lineno, text in string_literals(path):
            for name in RETIRED:
                # A string that is exactly the identifier is a registration,
                # not an instruction: LEGACY_RESUME_TOOLS has to name the
                # shim "submit_job" to answer approval cards recorded before
                # the rebuild. What this is looking for is the name embedded
                # in prose the model reads, so only longer strings count.
                if name in text and text.strip() != name:
                    offenders.append(f"{path.name}:{lineno} names {name}")
        rel = path.relative_to(REPO)
        check(f"{rel} names no retired tool in a string it emits",
              not offenders, "; ".join(offenders[:4]))

    print("\n== the tools that replaced them are bound ==")
    for name in ("set_geometry", "start_job_draft", "update_job_draft", "submit_draft"):
        check(f"{name} is bound", name in bound, f"bound={sorted(bound)}")

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
