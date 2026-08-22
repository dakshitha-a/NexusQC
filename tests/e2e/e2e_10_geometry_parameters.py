"""P9.2: geometry_parameters -- bond/angle/dihedral queries against a
tagged job or instrument-panel molecule frame.

Structural note matching e2e_09_plot_tools.py's own convention: refusal
cases (out-of-range/malformed atom indices) are exercised first, since
REFUSING IS THE PASS CONDITION there -- a value appearing would be the
bug -- then success cases for the single-geometry path and the
pes_1d/interp_pes/geometry_set ordered-table path. The batch/
wigner_spectra histogram path is NOT re-exercised live here: its
resolver (_resolve_batch_children/_geometry_parameters_histogram in
app/agent/tools.py) is structurally identical to the geometry_set path
this file DOES exercise live (same geometry_upload.parse_multi_frame_xyz
read, same per-geometry _validate_atom_indices/_compute_geometry_parameter
calls), and was verified directly against synthetic fixtures covering
success, the >=2-sample floor, and per-child heterogeneous-atom-count
skipping (see docs/trackers/2026-08-job-system-overhaul.md's P9.2 evidence) -- submitting real batch/
wigner_spectra jobs just to re-prove the same file-reading code path
would cost real compute time for no new coverage.

Run this AFTER e2e_08_job_matrix.py -- it works from jobs that already
exist in the account rather than creating its own for the single-geometry
case.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record  # noqa: E402


def find_completed_job(client, method: str = "hf", engine: str = "pyscf", min_atoms: int = 3):
    r = client.get("/api/jobs")
    r.raise_for_status()
    for j in r.json():
        if j.get("status") == "completed" and j.get("method") == method and j.get("engine") == engine:
            return j["job_id"]
    return None


def ask(client, text: str, label: str, timeout: float = 420):
    s = AgentSession.new(client, label=label)
    turn = s.say(text, timeout=timeout)
    calls = [a for n, a in turn.tools_requested() if n == "geometry_parameters"]
    texts = [c for n, c in turn.tools_executed() if n == "geometry_parameters"]
    s.close()
    return calls, texts, turn


def _submit_water_geometry_set(client) -> str | None:
    """Submits a 3-frame geometry_set directly via JobManager in the api
    container -- no compute, no worker (submit_geometry_set writes
    status='completed' immediately, see its own docstring) -- same "call
    the mechanism directly to manufacture test fixtures" precedent
    e2e_09_plot_tools.py's _submit_comparable_single_points already sets,
    for the identical reason: driving a live LLM turn just to build this
    file's INPUT would make an unrelated model miss look like a
    geometry_parameters bug."""
    code = """
import json
from app.chemistry.jobs.base import get_job_manager
frames = [
    {"symbols": ["O", "H", "H"], "coords": [[0,0,0],[0.90,0,0],[0.2554,0.8721,0]], "name": "pt1"},
    {"symbols": ["O", "H", "H"], "coords": [[0,0,0],[0.97,0,0],[0.2752,0.9394,0]], "name": "pt2"},
    {"symbols": ["O", "H", "H"], "coords": [[0,0,0],[1.10,0,0],[0.3123,1.0645,0]], "name": "pt3"},
]
job_id = get_job_manager().submit_geometry_set(frames, label="e2e geometry_parameters fixture")
print("@@@" + job_id)
"""
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(Path(__file__).resolve().parent.parent.parent),
        capture_output=True, text=True, timeout=60,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("@@@"):
            return line[3:].strip()
    print("submit_geometry_set stdout/stderr:", proc.stdout[-500:], proc.stderr[-500:])
    return None


def main() -> None:
    admin = admin_client()
    job_id = find_completed_job(admin)
    if not job_id:
        check("a completed hf/pyscf job exists to query (run e2e_08_job_matrix.py first)", False)
        summary(exit_on_failure=False)
        return
    print(f"Using job {job_id} for single-geometry cases.\n")

    # ------------------------------------------------ refusals (the point)
    calls, texts, turn = ask(
        admin, f"What's the bond length between atoms 1 and 9 in job {job_id}?",
        "e2e geo bad index",
    )
    joined = "\n".join(texts)
    refused = bool(calls) and "must be between" in joined and "PLOT_ARTIFACT" not in joined
    check("an out-of-range atom index refuses cleanly (names the real atom count), not a crash or a "
          "fabricated value", refused, f"calls={calls} :: {joined[:200]}")
    record("G-badindex", "PASS" if refused else "FAIL", job_id=job_id, text=joined[:300])

    calls2, texts2, turn2 = ask(
        admin, f"What's the dihedral angle between atoms 1, 2, 3 and 4 in job {job_id}?",
        "e2e geo bad dihedral",
    )
    joined2 = "\n".join(texts2)
    refused2 = bool(calls2) and ("needs exactly" in joined2 or "must be between" in joined2)
    check("a dihedral request on a 3-atom molecule (needs a 4th index that doesn't exist) refuses "
          "rather than fabricating a 4th atom", refused2, f"calls={calls2} :: {joined2[:200]}")
    record("G-baddihedral", "PASS" if refused2 else "FAIL", job_id=job_id, text=joined2[:300])

    # ------------------------------------------------ single-geometry success
    calls3, texts3, turn3 = ask(
        admin, f"What's the O-H1 bond length in job {job_id}?", "e2e geo bond",
    )
    joined3 = "\n".join(texts3)
    ok3 = bool(calls3) and "| Parameter | Atoms | Value | Unit |" in joined3 and "Å" in joined3
    check("a real bond-length query against a completed job returns a one-row table with a value",
          ok3, f"calls={calls3} :: {joined3[:250]}")
    record("G-bond", "PASS" if ok3 else "FAIL", job_id=job_id, text=joined3[:300])

    # ------------------------------------------------ ordered table (geometry_set)
    gset_id = _submit_water_geometry_set(admin)
    if not gset_id:
        check("geometry_set fixture submitted for the ordered-table case", False)
    else:
        calls4, texts4, turn4 = ask(
            admin, f"What's the O-H1 bond length for each geometry in job {gset_id}? Give me a table.",
            "e2e geo ordered table",
        )
        joined4 = "\n".join(texts4)
        ok4 = bool(calls4) and joined4.count("\n") >= 3 and "|" in joined4 and "PLOT_ARTIFACT" not in joined4
        check("a tagged geometry_set returns an ordered TABLE (one row per frame), not a histogram",
              ok4, f"calls={calls4} :: {joined4[:300]}")
        record("G-orderedtable", "PASS" if ok4 else "FAIL", job_id=gset_id, text=joined4[:400])

    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
