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


def job_context_summary(job_id: str) -> str:
    mgr = get_job_manager()
    status = mgr.status(job_id)
    if status["status"] in ("pending", "running"):
        return f"Job {job_id} is still {status['status']} ({status.get('message', '')})."

    result = mgr.result(job_id)
    if result is None:
        return f"Job {job_id} finished but no result was recorded; status={status}."
    if result["status"] == "failed":
        # Includes the original job_type/engine/params -- if this is about
        # to be retried (submit_job with retry_of_job_id=job_id), reuse
        # these exact job_type/engine and only change what the error
        # indicates is wrong; don't guess a different job_type from the
        # error text alone.
        spec = read_spec(job_id)
        spec_line = ""
        if spec:
            visible_params = {k: v for k, v in spec.get("params", {}).items() if not k.startswith("_")}
            spec_line = f"Original job: job_type={spec.get('method')}, engine={spec.get('engine')}, params={visible_params}\n"
        return (
            f"Job {job_id} FAILED.\n{spec_line}"
            f"Error detail (share the relevant part with the user, don't dump all of it):\n{result['error'][:2000]}"
        )

    return f"Job {job_id} completed. Results:\n{_summary_as_markdown_table(result['summary'])}"
