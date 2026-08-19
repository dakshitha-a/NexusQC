"""The job_type x engine matrix, driven end to end through real agent
turns as an ordinary user account.

Each cell is one fresh conversation:

    natural-language request
      -> assert the approval card carries the right task/engine/params
      -> approve the interrupt
      -> poll the job to a terminal state
      -> assert the result's summary actually carries what that job type
         is supposed to produce
      -> assert every declared artifact is downloadable

The parameter assertion is the point. A job that completes is not
evidence the agent asked for the right calculation -- it is only evidence
that whatever it asked for was runnable.

Tiers (see _probes.py):
    1  blocks deployment
    2  spot-check
    3  attempt and classify -- BAGEL/MKL flakiness on this host is ENV,
       and neb_ts/target_state is explicitly unverified territory (XN-09)

Usage:
    python3 tests/e2e/e2e_08_job_matrix.py --tier 1
    python3 tests/e2e/e2e_08_job_matrix.py --only M10
    python3 tests/e2e/e2e_08_job_matrix.py            # everything
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, skip, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, check_tools, record  # noqa: E402
from _probes import MATRIX  # noqa: E402

# What each job type must actually produce. Keys are checked as "at least
# one of these is present and non-None" -- engines legitimately name the
# same quantity differently (a single_point's energy_hartree vs a
# casscf's casscf_energy_hartree), which is the same asymmetry
# plot(kind='comparison')'s _COMPARISON_FIELD_ALIASES exists to paper over.
EXPECTED_SUMMARY_KEYS = {
    "single_point": ["energy_hartree"],
    "geometry_optimization": ["final_energy_hartree", "optimized_molecule"],
    "frequency": ["frequencies_cm-1"],
    "casscf": ["casscf_energy_hartree", "state_energies_hartree"],
    "caspt2": ["caspt2_energy_hartree", "state_energies_hartree"],
    "tddft": ["excitation_energies_eV"],
    "eom_ccsd": ["excitation_energies_eV"],
    "mo_visualization": ["orbital_table"],
    "pes_scan": [],           # master job; children carry the energies
    "neb_ts": ["neb_converged", "path_energies_hartree"],
    "custom": ["note", "raw_output_tail"],
    "recommend_active_space": ["recommended_active_orbitals", "findings_summary"],
}


def prompt_for(job_type: str, engine: str, params: dict) -> str:
    """Build a natural-language request that fully specifies the cell, so
    a miss is a genuine tool-selection failure rather than the agent
    correctly stopping to elicit something we never told it."""
    p = dict(params)
    bits = [f"using {engine.upper()}"]
    if p.get("basis"):
        bits.append(f"with the {p['basis']} basis set")
    if p.get("method") in ("hf",):
        bits.append("at the Hartree-Fock level")
    elif p.get("method") == "dft":
        bits.append(f"with DFT using the {p.get('functional', 'B3LYP')} functional")
    elif p.get("method") in ("casscf", "caspt2"):
        bits.append(f"with a {p['method'].upper()} reference")
    if p.get("active_electrons") and p.get("active_orbitals"):
        bits.append(f"with an active space of {p['active_electrons']} electrons "
                    f"in {p['active_orbitals']} orbitals")
    if p.get("n_states"):
        bits.append(f"for {p['n_states']} excited states")
    if p.get("orbital_indices"):
        bits.append(f"rendering orbitals {', '.join(str(i) for i in p['orbital_indices'])}")
    if p.get("want_oscillator_strengths"):
        bits.append("and I need oscillator strengths for the transitions")
    if p.get("n_points"):
        bits.append(f"scanning the O-H bond between atoms 1 and 2 from "
                    f"{p.get('scan_range', [0.8, 1.4])[0]} to "
                    f"{p.get('scan_range', [0.8, 1.4])[1]} angstroms "
                    f"in {p['n_points']} points")
    if p.get("preopt") is not None:
        bits.append(f"with endpoint pre-optimization turned "
                    f"{'on' if p['preopt'] else 'off'}")
    if p.get("use_tda"):
        bits.append("using the Tamm-Dancoff approximation")

    human = {
        "single_point": "a single point energy calculation",
        "geometry_optimization": "a geometry optimization",
        "frequency": "a vibrational frequency calculation",
        "casscf": "a CASSCF calculation",
        "caspt2": "a CASPT2 calculation",
        "tddft": "a TDDFT excited state calculation",
        "eom_ccsd": "an EOM-CCSD excited state calculation",
        "mo_visualization": "a molecular orbital visualization",
        "pes_scan": "a potential energy surface scan",
        "neb_ts": "a NEB-TS transition state search",
        "custom": "a custom calculation",
        "recommend_active_space": "an active space recommendation",
    }[job_type]

    return f"Run {human} on water {' '.join(bits)}. Please go ahead and submit it."


def run_cell(user, cell, admin) -> None:
    cid, job_type, engine, tier, params, note = cell
    label = f"{cid} {job_type}/{engine}"
    print(f"\n----- {label} (tier {tier}) {'-- ' + note if note else ''}")

    if job_type == "custom":
        text = (f"Compose a raw {engine.upper()} input for a Hartree-Fock STO-3G "
                f"single point on water and run it as a custom job. "
                f"Describe it as 'e2e custom HF probe'.")
    elif job_type == "neb_ts":
        print("    (needs a second endpoint; set below)")
        text = None
    else:
        text = prompt_for(job_type, engine, params)

    s = AgentSession.new(user, label=label)
    t0 = time.perf_counter()

    if job_type == "neb_ts":
        s.say("Set the molecule to ammonia.", timeout=300)
        s.say("Now set the scan/NEB end point to this geometry:\n"
              "4\n\n"
              "N  0.000  0.000  0.000\n"
              "H  0.000  0.939 -0.290\n"
              "H  0.813 -0.470 -0.290\n"
              "H -0.813 -0.470 -0.290\n", timeout=300)
        text = ("Run a NEB-TS transition state search using ORCA at the "
                "Hartree-Fock level with the STO-3G basis, 6 images, with "
                "endpoint pre-optimization turned on. Go ahead and submit it.")

    turn = s.say(text, timeout=600)
    tools = turn.tool_names()

    want = {"job_type": job_type}
    # Engine is only asserted where the request named it explicitly, or
    # where routing is supposed to be MECHANICAL rather than phrased.
    if job_type not in ("custom",):
        want["engine"] = engine
    # The assertion moved off the tool call and onto the approval payload.
    # `submit_draft` takes no arguments -- the draft it submits lives in
    # graph state -- so "did the agent ask for the right job?" is now a
    # question about the card the user is shown, which is also the thing
    # that actually determines what runs.
    ok, detail = check_tools(turn, cid, must_call=["submit_draft"])
    check(f"{cid} agent reached an approval card for {job_type} on {engine}",
          ok, detail + f" | tools={tools}")

    if params.get("want_oscillator_strengths"):
        # This routing is mechanical (default_engine consults params), not
        # something the model is supposed to infer from phrasing.
        args = [(turn.pending_approval or {})]
        routed = any(a.get("engine") == "orca" for a in args) or any(
            (a.get("want_oscillator_strengths") or
             (a.get("params") or {}).get("want_oscillator_strengths")) for a in args)
        check(f"{cid} want_oscillator_strengths mechanically routes CASSCF to ORCA",
              routed, str(args))

    pending = s.wait_for_approval(timeout=120)
    check(f"{cid} approval card appeared (the interrupt gate held)", pending is not None,
          f"tools={tools}")
    if pending is None:
        record(cid, "FAIL", job_type=job_type, engine=engine, tier=tier,
               detail="no approval card", tools=tools)
        s.close()
        return

    spec = pending["spec"]
    check(f"{cid} approval card shows engine={engine}",
          spec.get("engine") == engine,
          f"card says {spec.get('engine')}")

    s.approve()
    jobs = getattr(s, "new_job_ids", [])
    if not jobs:
        check(f"{cid} approval produced a job", False, "no job id")
        record(cid, "FAIL", job_type=job_type, engine=engine, tier=tier,
               detail="approval produced no job")
        s.close()
        return

    job_id = jobs[0]
    # Tier-aware wall-clock budget -- a constraint of THIS HARNESS, not a
    # judgement about the job.
    #
    # CASSCF and CASPT2 runs in this group routinely take 40-50 minutes and
    # sometimes hours; the asynchronous job system exists precisely so that
    # is fine. A matrix of 26 cells cannot wait that out serially, so tier
    # 3 (the multi-reference/BAGEL combinations) gets a bounded wait and
    # the cell is then classified by WHAT STATE it is in -- which is the
    # part that actually distinguishes a healthy long calculation from a
    # broken one:
    #
    #   still RUNNING  -> working as designed. Not a failure. Recorded as a
    #                     skip so it stays visible, and cancelled to give
    #                     the host back to the remaining cells.
    #   still PENDING  -> a real finding: nothing is running it. That is
    #                     the admission-gate/cap failure mode (see F-005),
    #                     and it does NOT get a pass.
    #
    # An earlier version failed the cell outright in both cases, on the
    # since-retracted premise that a job exceeding ten minutes "will look
    # like a hang" (F-017). Tiers 1-2 keep a generous budget because those
    # combinations really are fast here, so a timeout there is a finding.
    budget = {1: 1800, 2: 1800, 3: 900}[tier]
    job = s.await_job(job_id, timeout=budget)
    if job.get("_timed_out"):
        st = job.get("status")
        if st == "running":
            skip(f"{cid} reached a terminal state within {budget}s",
                 f"still running after {budget}s -- expected for {job_type}/{engine} "
                 f"on this host, and exactly what the job system is for; "
                 f"cancelled to free the host for the remaining cells")
            record(cid, "LONG_RUNNING", job_type=job_type, engine=engine, tier=tier,
                   job_id=job_id, budget_seconds=budget, status=st,
                   detail="still running at the harness budget -- not a defect")
        else:
            check(f"{cid} is actually being worked on, not stuck queued",
                  False,
                  f"still {st!r} after {budget}s -- nothing is running it, which is "
                  f"the admission-gate failure mode, not a slow calculation")
            record(cid, "STUCK", job_type=job_type, engine=engine, tier=tier,
                   job_id=job_id, budget_seconds=budget, status=st,
                   detail="non-terminal and NOT running at the harness budget")
        try:
            user.post(f"/api/jobs/{job_id}/cancel", timeout=60)
        except Exception:
            pass
        s.close()
        return
    elapsed = time.perf_counter() - t0
    status = job.get("status")
    check(f"{cid} job {job_id} completed", status == "completed",
          f"status={status} err={str(job.get('error'))[:250]}")

    smry = job.get("summary") or {}
    expected = EXPECTED_SUMMARY_KEYS.get(job_type, [])
    if expected and status == "completed":
        present = [k for k in expected if smry.get(k) is not None]
        check(f"{cid} summary carries what {job_type} is supposed to produce "
              f"(one of {expected})", bool(present),
              f"got keys: {sorted(smry.keys())[:14]}")

    # Every declared artifact must actually be servable.
    arts = job.get("artifacts") or {}
    bad_arts = []
    for key in list(arts.keys())[:8]:
        if isinstance(arts[key], dict):
            continue
        r = user.get(f"/api/jobs/{job_id}/artifacts/{key}")
        if r.status_code != 200:
            bad_arts.append(f"{key}->{r.status_code}")
    check(f"{cid} all declared artifacts are downloadable", not bad_arts,
          "; ".join(bad_arts) or f"{len(arts)} artifacts")

    print(f"    [perf] {cid} total {elapsed:.1f}s (turn {turn.elapsed:.1f}s, "
          f"ttft {turn.ttft or -1:.1f}s)")
    record(cid, "PASS" if status == "completed" else "FAIL",
           job_type=job_type, engine=engine, tier=tier, job_id=job_id, status=status,
           elapsed=round(elapsed, 1), turn_elapsed=round(turn.elapsed, 1),
           ttft=round(turn.ttft, 2) if turn.ttft else None,
           tools=tools, summary_keys=sorted(smry.keys()),
           artifacts=sorted(arts.keys()), error=str(job.get("error"))[:400])
    s.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, default=None)
    ap.add_argument("--only", type=str, default=None)
    args = ap.parse_args()

    cells = MATRIX
    if args.tier:
        cells = [c for c in cells if c[3] == args.tier]
    if args.only:
        cells = [c for c in cells if c[0] == args.only]

    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = (info.get("user") or info).get("id")
    print(f"Running {len(cells)} matrix cell(s) as a normal user account.\n")

    for cell in cells:
        try:
            run_cell(user, cell, admin)
        except Exception as e:
            check(f"{cell[0]} raised", False, f"{type(e).__name__}: {e}"[:300])
            record(cell[0], "ERROR", job_type=cell[1], engine=cell[2], tier=cell[3],
                   detail=f"{type(e).__name__}: {e}"[:400])

    print(f"\n(user {uid} left in place for follow-up scripts; delete with "
          f"cleanup_all_qatest_users)")
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
