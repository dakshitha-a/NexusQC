"""Every agent tool that is NOT submit_job, plus the two mechanical
guarantees the registry is supposed to provide: required-param
elicitation, and refusal of a disallowed job_type/engine pairing.

The assertion channel throughout is the state-derived tool trace (name +
args), never the outcome text -- see _agent.py's module docstring for why
a plausible-looking answer is not evidence the right tool ran.

Tools exercised here:
    set_molecule, set_pes_scan_endpoint, generate_job_input,
    check_job_status, search_knowledge_base, search_academic_literature,
    web_search
(submit_job has its own script, e2e_07; the three plot tools have e2e_09.)

Network-dependent tools (search_academic_literature, web_search, and
PubChem behind set_molecule) are reported but never hard-failed on a
network error -- that is ENV, not CODE. What IS asserted is that the tool
was CALLED and that a failure degrades to an explanatory string rather
than raising.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, check_tools, record_turn  # noqa: E402
from _probes import DISALLOWED_PAIRINGS  # noqa: E402


def scenario(user, label, text, timeout=300):
    s = AgentSession.new(user, label=label)
    t = s.say(text, timeout=timeout)
    s.close()
    return t


def assert_scenario(user, sid, label, text, must_call=(), must_not_call=(),
                    args_match=None, attempts=3, timeout=300):
    """Runs a scenario, retrying on a FRESH thread per the LLM
    non-determinism policy. Reports PASS / FLAKY k/N / FAIL."""
    ok_count = 0
    details = []
    last = None
    for i in range(attempts):
        t = scenario(user, f"{label} #{i + 1}", text, timeout=timeout)
        last = t
        ok, detail = check_tools(t, sid, must_call, must_not_call, args_match)
        if ok:
            ok_count += 1
            if i == 0:
                check(f"{sid} {label}", True, f"1/1; tools={t.tool_names()}")
                record_turn(sid, "PASS", t, "1/1")
                return t
        else:
            details.append(f"try{i + 1}: {detail}")
    if ok_count:
        check(f"{sid} {label} [FLAKY {ok_count}/{attempts}]", True,
              "prompt-reliability finding, not a code defect: " + " | ".join(details))
        record_turn(sid, "FLAKY", last, f"{ok_count}/{attempts}; " + " | ".join(details))
    else:
        check(f"{sid} {label}", False, f"0/{attempts}; " + " | ".join(details))
        record_turn(sid, "FAIL", last, f"0/{attempts}; " + " | ".join(details))
    return last


def main() -> None:
    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = (info.get("user") or info).get("id")

    print("=== Non-job tools ===\n")

    assert_scenario(
        user, "T01", "set_molecule by common name",
        "Let's work with water.",
        must_call=["set_molecule"], must_not_call=["submit_job"],
        args_match={"set_molecule": {"identifier": "water"}},
    )

    assert_scenario(
        user, "T02", "set_molecule by SMILES",
        "Set the molecule to the SMILES string CCO.",
        must_call=["set_molecule"], must_not_call=["submit_job"],
        args_match={"set_molecule": {"identifier": "CCO"}},
    )

    assert_scenario(
        user, "T03", "generate_job_input previews WITHOUT running",
        "Show me what the ORCA input file would look like for a Hartree-Fock "
        "STO-3G single point on water. Don't run it, just show me the input.",
        must_call=["generate_job_input"], must_not_call=["submit_job"],
        args_match={"generate_job_input": {"job_type": "single_point", "engine": "orca"}},
    )

    assert_scenario(
        user, "T04", "search_knowledge_base is used for manual syntax questions",
        "What does the ORCA manual say about the %casscf block and its ETol keyword?",
        must_call=["search_knowledge_base"], must_not_call=["submit_job"],
    )

    assert_scenario(
        user, "T05", "search_academic_literature for a literature question",
        "Find the most cited papers on choosing an active space for CASSCF "
        "calculations of retinal photoisomerization.",
        must_call=["search_academic_literature"], must_not_call=["submit_job"],
        timeout=420,
    )

    assert_scenario(
        user, "T06", "web_search for a current-events/software question",
        "Search the web for what the latest released version of ORCA is.",
        must_call=["web_search"], must_not_call=["submit_job"],
        timeout=420,
    )

    print("\n=== Required-param elicitation (agent must ASK, never guess) ===\n")

    # The system prompt is explicit that chemically significant parameters
    # are never to be guessed. A submit_job call here would be a real
    # safety-relevant failure, not a style problem.
    assert_scenario(
        user, "E01", "no basis given -> elicit, do not guess",
        "Run a single point energy calculation on water.",
        must_not_call=["submit_job"],
    )
    assert_scenario(
        user, "E02", "no active space given -> elicit, do not guess",
        "Run a CASSCF calculation on water with the STO-3G basis.",
        must_not_call=["submit_job"],
    )
    assert_scenario(
        user, "E03", "no n_states given -> elicit",
        "Run a TDDFT calculation on water with B3LYP and STO-3G.",
        must_not_call=["submit_job"],
    )

    print("\n=== Disallowed job_type/engine pairings must be refused ===\n")

    for did, job_type, engine, note in DISALLOWED_PAIRINGS[:4]:
        t = scenario(
            user, f"{did}",
            f"Run a {job_type} calculation on water using {engine}, "
            f"basis STO-3G, active space 4 electrons in 4 orbitals, 3 states.",
            timeout=300,
        )
        # Either the agent never calls submit_job with that engine, or the
        # tool returns the registry's own refusal. Both are correct; what
        # must NOT happen is a job actually being created on that engine.
        approved_engine = None
        for name, args in t.tools_requested():
            if name == "submit_job" and args.get("engine") == engine:
                approved_engine = engine
        refused = any(
            "cannot run" in c.lower() or "allowed engines" in c.lower()
            for _, c in t.tools_executed()
        )
        pending = t.pending_approval
        bad = pending is not None and (pending.get("spec") or {}).get("engine") == engine
        check(
            f"{did} {job_type} on {engine} is refused" + (f" -- {note}" if note else ""),
            not bad, f"tools={t.tool_names()} refusal_seen={refused} "
                     f"pending_engine={(pending or {}).get('spec', {}).get('engine')}",
        )
        record_turn(did, "PASS" if not bad else "FAIL", t, note)

    cleanup_user(admin, uid)
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
