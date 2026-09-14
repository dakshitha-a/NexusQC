"""The (task, subtype) x engine matrix, driven end to end through real
agent turns as an ordinary user account.

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

# What each (task, subtype) must actually produce. Keys are checked as "at
# least one of these is present and non-None".
#
# That "at least one" used to be doing much more work than it looks like:
# engines named the same quantity differently, so a ground-state energy was
# energy_hartree here, casscf_energy_hartree there and
# ground_state_ccsd_energy_hartree somewhere else, and the list had to name
# every spelling. Since the canonical vocabulary
# (app/chemistry/jobs/facts.py) there is one name per quantity, so these
# lists are alternatives between genuinely different RESULTS -- a CASSCF
# job reporting a set of roots rather than a single energy -- not between
# two names for one number.
#
# P2B.6: keyed on (task, subtype) rather than the full (task, subtype,
# method) triple, and rather than the v1 job_type this replaces. Multiple
# v1 job_types collapse onto one (task, subtype) here -- single_point,
# casscf, caspt2 and mo_visualization were four separate v1 job_types and
# are all single_point/gs now, so "gs" carries the union of what any of
# them can produce. That is deliberately looser than a v1 cell's single
# expected key: it is still "at least one of these present", so a genuine
# miss (no energy of any kind, no orbital_table when orbital_indices was
# asked for) still fails the check, it just no longer needs a separate
# dict entry per method sharing the same task/subtype -- verified this
# does not lose precision by reading pyscf_runner.py's run_casscf, which
# always writes state_energies_hartree (even a single-entry list when
# n_states=1/subtype=gs) alongside casscf_energy_hartree, so the "gs"
# entry below is exhaustive for both a plain and a CASSCF/CASPT2 subtype-gs
# job. eom_ccsd's distinct ground-state key lives inside the "ee" list, not
# as a separate dict entry, since it is a key inside one summary shape, not
# a different (task, subtype).
EXPECTED_SUMMARY_KEYS = {
    ("single_point", "gs"): [
        "total_energy_hartree", "state_energies_hartree", "orbital_table",
    ],
    ("opt", "min"): ["total_energy_hartree", "optimized_geometry"],
    ("freq", ""): ["frequencies_cm-1"],
    ("opt_freq", ""): ["frequencies_cm-1", "optimized_geometry"],
    ("single_point", "ee"): [
        "excitation_energies_eV", "total_energy_hartree",
    ],
    # The master's own summary is not empty, which this entry used to assume.
    # `scan_orchestrator.py` writes `n_points` and `energies_hartree` into it
    # unconditionally once the children land, and a completed pes_1d/ee master
    # read off disk carries coordinate, coordinate_values, energies_hartree,
    # relative_energies_eV and state_energies_per_image. Asserting the two
    # unconditional ones is a real check where `[]` was none at all.
    ("pes_1d", ""): ["n_points", "energies_hartree"],
    ("pes_1d", "ee"): ["n_points", "energies_hartree", "state_energies_per_image"],
    # interp_pes runs through the same orchestrator (scan_orchestrator.py
    # dispatches on task in ("pes_1d", "interp_pes")), so the same keys apply.
    ("interp_pes", ""): ["n_points", "energies_hartree"],
    ("interp_pes", "ee"): ["n_points", "energies_hartree", "state_energies_per_image"],
    ("neb_ts", ""): ["neb_converged", "path_energies_hartree"],
    ("blind", ""): ["note", "raw_output_tail"],
    # Keyed on "autocas" until 2026-09-06, a subtype the registry stopped
    # having when the 2026-09-02 rebuild replaced the AVAS pilot. Because
    # _probes.py's cell was keyed the same stale way, the two tables agreed
    # with each other and the taxonomy check passed while neither matched the
    # registry.
    ("cas_reco", ""): [
        "recommended_active_orbitals", "recommended_active_electrons",
        "findings_summary",
    ],
    # One entry per requested state / pair, plus the scalar-per-entry views
    # an LLM reads instead of the withheld per-atom vectors. See
    # app/chemistry/jobs/derivatives.py for the full shape.
    ("single_point", "grad"): ["gradients", "target_states", "gradient_norms_hartree_per_bohr"],
    ("single_point", "nac"): ["couplings", "state_pairs", "nac_norms_hartree_per_bohr"],
    # Phase 6. Same underlying runner (geometry_optimization) as opt/min, so
    # the same success keys apply; "constraints" is the one addition, only
    # ever present when the request actually carried one.
    ("opt", "constrained"): ["total_energy_hartree", "optimized_geometry"],
    # Phase 6. ORCA's %CONICAL path writes a single total energy plus
    # ci_energy_diff_hartree; BAGEL's gradient-projection MECP writes
    # state_energies_hartree instead (no single total energy when there is
    # more than one root) -- "at least one of these" covers both shapes.
    ("opt", "ci"): ["optimized_geometry", "total_energy_hartree", "state_energies_hartree"],
}


def _human_description(task: str, subtype: str, params: dict) -> str:
    """The natural-language phrase for one (task, subtype) cell.

    P2B.6: the v1 job_type string used to double as both "what to ask for"
    and "which summary shape to expect" -- one lookup did both jobs because
    a v1 job_type was fine-grained enough to name a method too ("casscf",
    "tddft"). v2's (task, subtype) is coarser on purpose (single_point/gs
    covers a plain energy, a CASSCF energy AND an MO-visualization
    request), so the phrase has to be picked from method/params as well,
    not from task/subtype alone.
    """
    if task == "single_point" and subtype == "gs":
        method = params.get("method")
        if method in ("casscf", "caspt2"):
            return f"a {method.upper()} calculation"
        if params.get("orbital_indices"):
            return "a molecular orbital visualization"
        return "a single point energy calculation"
    if task == "single_point" and subtype == "ee":
        return ("an EOM-CCSD excited state calculation" if params.get("method") == "eom_ccsd"
                else "a TDDFT excited state calculation")
    if task == "single_point" and subtype == "grad":
        return ("an excited-state energy gradient" if params.get("target_state")
                else "a ground-state energy gradient")
    if task == "single_point" and subtype == "nac":
        return "a non-adiabatic coupling calculation"
    return {
        ("opt", "min"): "a geometry optimization",
        ("opt", "constrained"): "a constrained geometry optimization",
        ("opt", "ci"): "a conical-intersection optimization",
        ("freq", ""): "a vibrational frequency calculation",
        ("opt_freq", ""): "a geometry optimization followed by a frequency calculation",
        ("pes_1d", ""): "a potential energy surface scan",
        ("neb_ts", ""): "a NEB-TS transition state search",
        ("blind", ""): "a blind job -- an input run verbatim",
        ("cas_reco", ""): "an active space recommendation",
        ("pes_1d", "ee"): "an excited-state potential energy surface scan",
        ("interp_pes", ""): "an interpolated path scan between two structures",
        ("interp_pes", "ee"): (
            "an excited-state interpolated path scan between two structures"),
    }[(task, subtype)]


def prompt_for(task: str, subtype: str, engine: str, params: dict) -> str:
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
        # Phrased per method, because `n_states` genuinely means two
        # different things and this prompt is supposed to specify the cell
        # unambiguously. For a multireference method it counts the
        # state-averaged roots INCLUDING the ground state; for a
        # single-reference one it counts excited states above it.
        #
        # Saying "for 2 excited states" on a CASSCF cell asks for something
        # the cell's own params do not describe -- and the agent noticed,
        # which is how this was found: it built the draft, then stopped
        # before the approval card to point out that n_states=2 gives the
        # ground state plus one excited state, not two. That is the
        # registry's multireference caveat working exactly as intended, so
        # the prompt is what needed fixing, not the agent.
        if p.get("method") in ("casscf", "caspt2"):
            bits.append(f"state-averaged over {p['n_states']} roots "
                        f"(the ground state included)")
        else:
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
    if p.get("target_state"):
        bits.append(f"on the S{p['target_state']} excited state")
    if p.get("state_pairs"):
        s1, s2 = p["state_pairs"][0]
        bits.append(f"between states S{s1 - 1} and S{s2 - 1} (1-based including the ground state)")
    if p.get("constraints"):
        c = p["constraints"][0]
        atoms = "-".join(str(a) for a in c["atoms"])
        bits.append(f"holding the {c['type']} between atoms {atoms} fixed at {c['value']}")
    if p.get("target_state_2"):
        bits.append(f"finding the conical intersection between the ground state and S{p['target_state_2']}")

    human = _human_description(task, subtype, p)
    return f"Run {human} on water {' '.join(bits)}. Please go ahead and submit it."


def run_cell(user, cell, admin) -> None:
    cid, task, subtype, engine, tier, params, note = cell
    task_label = f"{task}/{subtype}" if subtype else task
    label = f"{cid} {task_label}/{engine}"
    print(f"\n----- {label} (tier {tier}) {'-- ' + note if note else ''}")

    if task == "blind":
        text = (f"Compose a raw {engine.upper()} input for a Hartree-Fock STO-3G "
                f"single point on water and run it verbatim as a blind job. "
                f"Describe it as 'e2e blind HF probe'.")
    elif task == "neb_ts":
        print("    (needs a second endpoint; set below)")
        text = None
    else:
        text = prompt_for(task, subtype, engine, params)

    s = AgentSession.new(user, label=label)
    t0 = time.perf_counter()

    if task == "neb_ts":
        # Ammonia inversion, and the end point has to be the OTHER pyramid.
        #
        # This cell reported `RuntimeError: ORCA exited with code 2` through
        # the whole 2026-09 review and was carried into the fix phase as an
        # ENV-versus-CODE question. It was neither. The end point used to have
        # the nitrogen at the origin with all three hydrogens at z = -0.290,
        # which puts the nitrogen on the SAME side of the H3 plane as the start
        # geometry does. The two endpoints were therefore the same pyramid
        # written twice, the pre-optimisation relaxed both to the same minimum
        # at -55.45542 Eh, and ORCA said so in as many words: "No barrier was
        # found. Skipping NEB-TS run here." A NEB with no barrier between its
        # endpoints has nothing to find.
        #
        # Inverting the sign of z on the hydrogens puts the nitrogen below
        # their plane instead, which is the umbrella flipped over, and the path
        # between the two runs through the planar D3h transition state that
        # ammonia inversion is the textbook example of.
        s.say("Set the molecule to ammonia.", timeout=300)
        s.say("Now set the scan/NEB end point to this geometry:\n"
              "4\n\n"
              "N  0.000  0.000  0.000\n"
              "H  0.000  0.939  0.290\n"
              "H  0.813 -0.470  0.290\n"
              "H -0.813 -0.470  0.290\n", timeout=300)
        text = ("Run a NEB-TS transition state search using ORCA at the "
                "Hartree-Fock level with the STO-3G basis, 6 images, with "
                "endpoint pre-optimization turned on. Go ahead and submit it.")

    turn = s.say(text, timeout=600)
    tools = turn.tool_names()

    # The assertion moved off the tool call and onto the approval payload.
    # `submit_draft` takes no arguments -- the draft it submits lives in
    # graph state -- so "did the agent ask for the right job?" is a question
    # about the card the user is shown, which is also the thing that actually
    # determines what runs. The comment said so; the code still required
    # `submit_draft` by name, and that requirement is now wrong.
    #
    # `run_when_ready=True` is the path the system prompt calls the ordinary
    # case: the draft goes to the approval card by itself once it is READY,
    # and `submit_draft` is only for the case where the caller deliberately
    # did not set it. So on the ordinary path the agent correctly never calls
    # it. Measured 2026-09-06: twelve tier-1 cells failed this check while the
    # very next check confirmed the card appeared, the job completed, its
    # summary carried the right keys and its artifacts downloaded. The test
    # was asserting against a mechanism the prompt tells the agent not to use.
    #
    # What every path does share is `start_job_draft`: there is no way to
    # reach a card without one. That is what is required here now, and whether
    # a card actually appeared is the next check's business.
    ok, detail = check_tools(turn, cid, must_call=["start_job_draft"])
    check(f"{cid} agent drafted a job for {task_label} on {engine}",
          ok, detail + f" | tools={tools} timed_out={turn.timed_out} "
          f"elapsed={turn.elapsed:.0f}s")

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
    # When submit_draft was called and NO card appeared, the tool returned a
    # message instead of pausing -- and that message says why. Reporting the
    # tool list alone leaves the two possibilities ("the model never
    # submitted" and "the submit was refused, here is the reason")
    # indistinguishable, which cost a full round of guessing the first time
    # this failed intermittently.
    # Whether the turn was cut off by the harness rather than ended by the
    # model. Without this, "the model stopped after three tools" and "we
    # stopped it after three tools" are the same line in the report -- and
    # M10, the cell the matrix itself labels the SLOW probe, kept producing
    # exactly that ambiguity.
    card_detail = f"tools={tools} timed_out={turn.timed_out} elapsed={turn.elapsed:.0f}s"
    if pending is None and "submit_draft" in tools:
        replies = [c for n, c in turn.tools_executed() if n == "submit_draft"]
        card_detail += (f"\n         submit_draft replied: "
                        f"{replies[-1][:400] if replies else '<no ToolMessage>'}")
    check(f"{cid} approval card appeared (the interrupt gate held)", pending is not None,
          card_detail)
    if pending is None:
        record(cid, "FAIL", task=task_label, engine=engine, tier=tier,
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
        record(cid, "FAIL", task=task_label, engine=engine, tier=tier,
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
                 f"still running after {budget}s -- expected for {task_label}/{engine} "
                 f"on this host, and exactly what the job system is for; "
                 f"cancelled to free the host for the remaining cells")
            record(cid, "LONG_RUNNING", task=task_label, engine=engine, tier=tier,
                   job_id=job_id, budget_seconds=budget, status=st,
                   detail="still running at the harness budget -- not a defect")
        else:
            check(f"{cid} is actually being worked on, not stuck queued",
                  False,
                  f"still {st!r} after {budget}s -- nothing is running it, which is "
                  f"the admission-gate failure mode, not a slow calculation")
            record(cid, "STUCK", task=task_label, engine=engine, tier=tier,
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
    expected = EXPECTED_SUMMARY_KEYS.get((task, subtype), [])
    if expected and status == "completed":
        present = [k for k in expected if smry.get(k) is not None]
        check(f"{cid} summary carries what {task_label} is supposed to produce "
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
           task=task_label, engine=engine, tier=tier, job_id=job_id, status=status,
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
        cells = [c for c in cells if c[4] == args.tier]
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
            task_label = f"{cell[1]}/{cell[2]}" if cell[2] else cell[1]
            record(cell[0], "ERROR", task=task_label, engine=cell[3], tier=cell[4],
                   detail=f"{type(e).__name__}: {e}"[:400])

    print(f"\n(user {uid} left in place for follow-up scripts; delete with "
          f"cleanup_all_qatest_users)")
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
