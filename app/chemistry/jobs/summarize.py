"""Human-readable summary of a single job's current state, factored out of
app/agent/tools.py's check_job_status so the exact same text backs both the
agent's own status-check tool and the "attach jobs to a prompt" feature
(server/routes/chat.py), which needs identical wording without going
through a tool call.
"""
from __future__ import annotations

from app.chemistry.jobs.base import get_job_manager, read_spec


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

    return f"Job {job_id} completed. Results:\n{result['summary']}"
