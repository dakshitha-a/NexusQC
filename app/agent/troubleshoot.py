"""Composing the one message that starts a troubleshooting turn.

This replaces auto-retry. The old behaviour was that a failed job silently
started an agent turn which investigated and resubmitted a corrected job on
its own initiative, up to a hard cap. Two things were wrong with it. It
spent someone's compute on a guess they never agreed to -- and on this host
a single CASSCF run can be hours -- and it made the failure invisible:
the user saw a new approval card without ever being told plainly that the
previous job had died.

Now a failure produces a notice and nothing else. Only if the user presses
Troubleshoot does an investigation turn begin, and this module composes the
message that starts it.

**The evidence is gathered mechanically, not by the model.** The last 25
lines of the job's real output are read off disk here and put in the
message, rather than leaving the model to call `check_job_status` and hope
it asks for the right thing. A model deciding what evidence to look at is a
model that can decide to look at none.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.chemistry.jobs.base import read_result, read_spec

# How much raw output to carry into the turn. Enough to hold an engine's
# error block and the lines that led to it, short enough that it cannot
# crowd out the conversation in the model's context window.
TAIL_LINES = 25


def _tail_of_file(path: str, n: int = TAIL_LINES) -> Optional[str]:
    try:
        p = Path(path)
        if not p.exists():
            return None
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return None
    if not lines:
        return None
    return "\n".join(lines[-n:])


def raw_output_tail(job_id: str, n: int = TAIL_LINES) -> tuple[Optional[str], str]:
    """(tail, where_it_came_from).

    Three sources, in descending order of fidelity. ORCA and BAGEL write a
    real output file, which is the best evidence available. PySCF runs
    in-process and writes no such file, so a failed PySCF job's evidence is
    the captured traceback instead -- which is why this returns the source
    alongside the text rather than pretending they are the same thing.
    """
    result = read_result(job_id) or {}
    artifacts = result.get("artifacts") or {}

    raw_path = artifacts.get("raw_output")
    if isinstance(raw_path, str):
        tail = _tail_of_file(raw_path, n)
        if tail:
            return tail, f"last {n} lines of the engine's raw output"

    summary = result.get("summary") or {}
    if summary.get("raw_output_tail"):
        text = str(summary["raw_output_tail"])
        return "\n".join(text.splitlines()[-n:]), "the captured tail of the engine's output"

    error = result.get("error")
    if error:
        return "\n".join(str(error).splitlines()[-n:]), "the captured Python traceback (this engine runs in-process and writes no output file)"

    return None, "no output was captured"


def compose_troubleshoot_message(job_id: str) -> Optional[str]:
    """The synthetic HumanMessage text for a troubleshooting turn, or None
    if this job did not fail.

    Deliberately a HumanMessage rather than a system-prompt change: it is a
    one-off instruction about one job, and the conversation should show
    why the agent suddenly started investigating. The "(system notice, not
    from the user)" prefix is the same convention job_watcher.py already
    uses for its injected notices, so the frontend renders it as a notice
    rather than as words the user typed.
    """
    result = read_result(job_id) or {}
    if result.get("status") != "failed":
        return None

    spec = read_spec(job_id) or {}
    job_type = spec.get("method", "unknown")
    engine = spec.get("engine", "unknown")
    params = spec.get("params") or {}
    tail, source = raw_output_tail(job_id)

    described = ", ".join(
        f"{k}={v!r}" for k, v in sorted(params.items())
        if not k.startswith("_") and v is not None
    ) or "(no parameters recorded)"

    parts = [
        f"(system notice, not from the user) The user has asked you to troubleshoot "
        f"job {job_id}, a '{job_type}' job on {engine} that FAILED.",
        f"Its parameters were: {described}.",
    ]
    if tail:
        parts.append(
            f"Here is {source}, included mechanically so you do not have to go "
            f"looking for it:\n\n```\n{tail}\n```"
        )
    else:
        parts.append(
            "No output was captured for this job, so diagnose from the parameters "
            "above and say plainly that the engine produced nothing to go on."
        )
    parts.append(
        "Work out what went wrong. Consult search_knowledge_base(doc_type='manual') "
        "for the engine's own documentation on the keywords involved, and web_search "
        "for the specific error text if that is not enough -- not "
        "search_academic_literature, which covers published papers rather than "
        "software errors. Then explain to the user, in plain language, what failed "
        "and why. If you can propose a corrected job, build it with start_job_draft "
        "and submit_draft so they get an approval card showing exactly what changed; "
        "if you cannot, say "
        "so and ask them how they would like to proceed rather than guessing."
    )
    return " ".join(parts[:2]) + "\n\n" + "\n\n".join(parts[2:])
