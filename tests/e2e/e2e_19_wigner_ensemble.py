"""Drives a real wigner_spectra ("nuclear ensemble spectrum") job end to
end through the actual conversational agent, not a direct JobManager
call. Deferred by P2B.2+P2B.4 and P2B.6 -- see docs/TRACKER.md -- because
wigner_spectra's own submission path (JobManager.submit_ensemble /
EnsembleOrchestrator's child dispatch) was only unit-verified up to that
point, unlike pes_1d's submit_scan path which reg2b_02_scan_dispatch_e2e.py
already drives for real. This is the live-stack counterpart: a genuine
two-turn conversation (source frequency job, then the ensemble job that
samples it), approved through the real interrupt gate, polled to a real
terminal state, with the pooled spectrum's summary and artifacts checked.

Not added to e2e_08_job_matrix.py's MATRIX because that table drives ONE
turn per cell; wigner_spectra genuinely needs two (a completed frequency
job to sample from), which is exactly why the whole cell had been deferred
rather than shoehorned into the single-turn shape.

Run: python3 tests/e2e/e2e_19_wigner_ensemble.py
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, check_tools, record  # noqa: E402

N_SAMPLES = 5
COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def _ensemble_indices(master_id: str) -> list[int]:
    """The `_ensemble_index` recorded on every real sub-job spec.json under
    this master, read in-container. A dupe here means two sub-jobs were
    dispatched for the same sample -- the discriminating check for the
    submit_ensemble/EnsembleOrchestrator double-dispatch race, since a run
    can come out with the right final n_dispatched count by luck even when
    a duplicate genuinely happened (e.g. one duplicate plus one dropped)."""
    code = f'''
import json
from app.chemistry.jobs.base import sub_job_ids_of, read_spec
subs = sub_job_ids_of("{master_id}")
idx = [read_spec(s)["params"].get("_ensemble_index") for s in subs]
print(json.dumps(idx))
'''
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    global N_SAMPLES
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-samples", type=int, default=N_SAMPLES,
                     help="Sample count for the ensemble -- a larger value widens the "
                          "submit_ensemble/EnsembleOrchestrator dispatch race's window "
                          "(the initial-wave dispatch loop takes proportionally longer, "
                          "giving the orchestrator's 3s poll tick more chances to land "
                          "inside it) without changing what's being tested.")
    args = ap.parse_args()
    N_SAMPLES = args.n_samples

    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = (info.get("user") or info).get("id")

    s = AgentSession.new(user, label="e2e_19 wigner ensemble")

    print("\n----- step 1: source frequency job (water, HF/STO-3G, PySCF)")
    turn1 = s.say(
        "Run a vibrational frequency calculation on water using PySCF at the "
        "Hartree-Fock level with the STO-3G basis. Please go ahead and submit it.",
        timeout=300,
    )
    ok, detail = check_tools(turn1, "W19-freq", must_call=["submit_draft"])
    check("W19-freq agent reached an approval card for the source frequency job",
          ok, detail + f" | tools={turn1.tool_names()}")

    pending1 = s.wait_for_approval(timeout=120)
    check("W19-freq approval card appeared", pending1 is not None,
          f"tools={turn1.tool_names()}")
    if pending1 is None:
        record("W19", "FAIL", detail="no approval card for source frequency job")
        s.close()
        cleanup_user(admin, uid)
        summary()
        return

    s.approve()
    freq_jobs = getattr(s, "new_job_ids", [])
    check("W19-freq approval produced a job", bool(freq_jobs), "no job id")
    if not freq_jobs:
        record("W19", "FAIL", detail="approving the frequency draft produced no job")
        s.close()
        cleanup_user(admin, uid)
        summary()
        return

    freq_job_id = freq_jobs[0]
    freq_job = s.await_job(freq_job_id, timeout=300)
    freq_status = freq_job.get("status")
    check("W19-freq source job completed", freq_status == "completed",
          f"status={freq_status} err={str(freq_job.get('error'))[:250]}")
    if freq_status != "completed":
        record("W19", "FAIL", job_id=freq_job_id, status=freq_status,
               detail="source frequency job did not complete")
        s.close()
        cleanup_user(admin, uid)
        summary()
        return

    print(f"    source frequency job {freq_job_id} completed")

    print("\n----- step 2: wigner_spectra ensemble sampling that job")
    turn2 = s.say(
        f"Now run a nuclear ensemble (Wigner) spectrum, sampling {N_SAMPLES} geometries "
        f"from frequency job {freq_job_id}. Use PySCF at the TDDFT level with the B3LYP "
        f"functional and the STO-3G basis, computing 3 excited states. Please go ahead "
        f"and submit it.",
        timeout=600,
    )
    ok, detail = check_tools(turn2, "W19-ensemble", must_call=["submit_draft"])
    check("W19-ensemble agent reached an approval card for the ensemble job",
          ok, detail + f" | tools={turn2.tool_names()} timed_out={turn2.timed_out}")

    pending2 = s.wait_for_approval(timeout=120)
    check("W19-ensemble approval card appeared", pending2 is not None,
          f"tools={turn2.tool_names()}")
    if pending2 is None:
        record("W19", "FAIL", job_id=freq_job_id, detail="no approval card for ensemble job")
        s.close()
        cleanup_user(admin, uid)
        summary()
        return

    spec2 = pending2["spec"]
    check("W19-ensemble approval card is a wigner_spectra draft",
          spec2.get("task") == "wigner_spectra", f"card says task={spec2.get('task')}")
    check("W19-ensemble approval card carries the source frequency job id",
          spec2.get("params", {}).get("source_frequency_job_id") == freq_job_id,
          f"card params={spec2.get('params')}")

    s.approve()
    ensemble_jobs = getattr(s, "new_job_ids", [])
    check("W19-ensemble approval produced a master job", bool(ensemble_jobs), "no job id")
    if not ensemble_jobs:
        record("W19", "FAIL", job_id=freq_job_id, detail="approving the ensemble draft produced no job")
        s.close()
        cleanup_user(admin, uid)
        summary()
        return

    master_id = ensemble_jobs[0]
    print(f"    master job {master_id} submitted, polling to terminal...")
    master = s.await_job(master_id, timeout=1200)
    master_status = master.get("status")
    check("W19-ensemble master job completed", master_status == "completed",
          f"status={master_status} err={str(master.get('error'))[:250]}")

    smry = master.get("summary") or {}
    print(f"    master summary keys: {sorted(smry.keys())}")
    check("W19-ensemble summary reports the requested sample count",
          smry.get("n_samples") == N_SAMPLES, f"n_samples={smry.get('n_samples')}")
    check("W19-ensemble every sample was dispatched",
          smry.get("n_dispatched") == N_SAMPLES, f"n_dispatched={smry.get('n_dispatched')}")
    check("W19-ensemble every sample reached a terminal state",
          smry.get("n_complete") == N_SAMPLES, f"n_complete={smry.get('n_complete')}")
    check("W19-ensemble the pool actually produced usable (energy, oscillator strength) pairs",
          bool(smry.get("n_completed")), f"n_completed={smry.get('n_completed')} plot_error={smry.get('plot_error')}")

    indices = _ensemble_indices(master_id)
    print(f"    sub-job _ensemble_index values: {sorted(indices)}")
    check("W19-ensemble every sub-job has a distinct _ensemble_index (no double-dispatch)",
          len(indices) == len(set(indices)),
          f"indices={sorted(indices)} -- a repeated value proves the same sample was dispatched twice")
    check("W19-ensemble the dispatched indices are exactly 0..N-1 (nothing skipped either)",
          sorted(indices) == list(range(N_SAMPLES)),
          f"indices={sorted(indices)} expected={list(range(N_SAMPLES))}")

    arts = master.get("artifacts") or {}
    print(f"    master artifacts: {sorted(arts.keys())}")
    for key in ("ensemble_xyz", "ensemble_spectrum", "ensemble_spectrum_data"):
        check(f"W19-ensemble artifact '{key}' is declared",
              key in arts, f"declared artifacts={sorted(arts.keys())}")

    bad_arts = []
    for key in arts:
        if isinstance(arts[key], dict):
            continue
        r = user.get(f"/api/jobs/{master_id}/artifacts/{key}")
        if r.status_code != 200:
            bad_arts.append(f"{key}->{r.status_code}")
    check("W19-ensemble all declared artifacts are downloadable", not bad_arts,
          "; ".join(bad_arts) or f"{len(arts)} artifacts")

    record("W19", "PASS" if master_status == "completed" and not bad_arts else "FAIL",
           freq_job_id=freq_job_id, master_job_id=master_id, status=master_status,
           summary_keys=sorted(smry.keys()), artifacts=sorted(arts.keys()))

    s.close()
    cleanup_user(admin, uid)
    summary()


if __name__ == "__main__":
    main()
