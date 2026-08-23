"""Human-readable summary of a single job's current state, factored out of
app/agent/tools.py's check_job_status so the exact same text backs both the
agent's own status-check tool and the "attach jobs to a prompt" feature
(server/routes/chat.py), which needs identical wording without going
through a tool call.
"""
from __future__ import annotations

from app.chemistry.jobs.base import get_job_manager, read_spec


def _format_summary_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        # A list of lists is bracketed per inner list rather than flattened.
        # An excited-state scan's `state_energies_per_image` is exactly this
        # shape -- one list of per-state energies per image -- and the plain
        # recursive comma-join turned it into a single undifferentiated run
        # of numbers with no way to tell where one image ended and the next
        # began. This text IS the model's input when a job is attached to a
        # prompt, so "what are the excited-state energies along this path?"
        # was being answered from a flattened blob.
        if any(isinstance(v, list) for v in value):
            return "; ".join(
                f"[{_format_summary_value(v)}]" if isinstance(v, list)
                else _format_summary_value(v)
                for v in value
            )
        return ", ".join(_format_summary_value(v) for v in value)
    return str(value)


def _summary_as_markdown_table(summary: dict) -> str:
    """Renders a completed job's summary dict as a GFM table instead of a
    raw Python dict repr -- this text becomes part of the LLM's own input
    (injected as a synthetic HumanMessage when a job is attached to a
    prompt, see server/routes/chat.py's _run_turn), so giving it already-
    tabular structure here reinforces the system prompt's "prefer tables
    when presenting data" instruction rather than relying on the model to
    reformat a Python dict dump on its own."""
    if not summary:
        return "(no summary fields)"
    rows = "\n".join(f"| {k} | {_format_summary_value(v)} |" for k, v in summary.items())
    return f"| field | value |\n|---|---|\n{rows}"


def _spec_line(job_id: str) -> str:
    """The job's own job_type/engine/params, as one line.

    Included for COMPLETED jobs as well as failed ones. It used to appear
    only in the failed branch, which left a real gap: a completed job's
    summary dict carries none of its own input settings (no method, no
    basis, no functional -- verified against real frequency and single-point
    results on disk), and this function is the whole of what the agent can
    see about an attached job, since check_job_status returns it too. So a
    perfectly ordinary request like "run this again with a bigger basis" or
    "use the same method and basis as the attached job" was unanswerable
    from any tool the agent has, and the model's only options were to ask
    or to invent a level of theory. Inventing one is not caught by anything
    downstream -- the approval card faithfully shows whatever was picked,
    and a user who trusts their own phrasing reads it as inherited.

    Params starting with "_" stay hidden; those are internal plumbing
    (_job_dir, _raw_input, ...) that would only add noise.
    """
    spec = read_spec(job_id)
    if not spec:
        return ""
    visible_params = {k: v for k, v in spec.get("params", {}).items() if not k.startswith("_")}
    # `job_type=` here reported spec["method"] -- the level of theory, not
    # the kind of job. So a pes_1d scan read back as "job_type=dft", an opt
    # as "dft", a freq as "dft" and a cas_reco as "casscf", each of them
    # contradicting what submit_draft had printed seconds earlier. The two
    # axes have been separate since registry v2; this line had not caught up.
    task = spec.get("task") or ""
    subtype = spec.get("subtype") or ""
    task_name = f"{task}/{subtype}" if subtype else task
    return (f"Original job: task={task_name}, method={spec.get('method')}, "
            f"engine={spec.get('engine')}, params={visible_params}\n")


def job_context_summary(job_id: str) -> str:
    mgr = get_job_manager()
    status = mgr.status(job_id)
    if status["status"] in ("pending", "running"):
        return f"Job {job_id} is still {status['status']} ({status.get('message', '')})."

    result = mgr.result(job_id)
    if result is None:
        return f"Job {job_id} finished but no result was recorded; status={status}."
    if result["status"] == "failed":
        # If the user asks for this to be troubleshooting-corrected, reuse
        # these exact job_type/engine and only change what the error
        # indicates is wrong; don't guess a different job_type from the
        # error text alone.
        return (
            f"Job {job_id} FAILED.\n{_spec_line(job_id)}"
            f"Error detail (share the relevant part with the user, don't dump all of it):\n{result['error'][:2000]}"
        )

    return (
        f"Job {job_id} completed.\n{_spec_line(job_id)}"
        f"Results:\n{_summary_as_markdown_table(result['summary'])}"
    )
