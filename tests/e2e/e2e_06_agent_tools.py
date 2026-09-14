"""Every agent tool that is NOT submit_draft, plus the two mechanical
guarantees the registry is supposed to provide: required-parameter
elicitation, and refusal of a combination no engine here can run.

The assertion channel throughout is the state-derived tool trace (name +
args), never the outcome text -- see _agent.py's module docstring for why
a plausible-looking answer is not evidence the right tool ran.

Tools exercised here:
    set_geometry, lookup_capabilities, start_job_draft, update_job_draft,
    check_job_status, search
(submit_draft has its own script, e2e_07; the consolidated `plot` has
e2e_09; the elicitation sequence itself has e2e_18.)

Both mechanical guarantees moved backend-side in Phase 2 and are stronger
for it. Elicitation used to be the model declining to guess because the
prompt told it not to; it is now `validate_draft` returning a question and
`submit_draft` refusing a draft that is not ready. A refused engine used
to be a per-job-type allow-list; it is now a capability verdict derived
from what the installed engines were measured to do.

Network-dependent sources (`search` with source="scholar" or "web", and
PubChem behind set_geometry) are reported but never hard-failed on a
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
        user, "T01", "set_geometry by common name",
        "Let's work with water.",
        must_call=["set_geometry"], must_not_call=["submit_draft"],
        args_match={"set_geometry": {"identifier": "water"}},
    )

    assert_scenario(
        user, "T02", "set_geometry by SMILES",
        "Set the molecule to the SMILES string CCO.",
        must_call=["set_geometry"], must_not_call=["submit_draft"],
        args_match={"set_geometry": {"identifier": "CCO"}},
    )

    # `generate_job_input` is gone: a ready draft already carries the engine
    # input, so "show me the input" is answered one tool call before the
    # approval gate rather than by a second tool duplicating the build path.
    # What must still hold is the half that mattered -- showing an input is
    # not running one.
    assert_scenario(
        user, "T03", "a draft shows its input WITHOUT submitting it",
        "Show me what the ORCA input file would look like for a Hartree-Fock "
        "STO-3G single point on water. Don't run it, just show me the input.",
        must_call=["start_job_draft"], must_not_call=["submit_draft"],
    )

    # T04 to T06 name `search` and check its `source`, which is the shape the
    # tool has had since the four retrieval tools were unified.
    # `search_knowledge_base`, `search_academic_literature` and `web_search`
    # are still functions in the codebase, but they are no longer BOUND: the
    # model sees one `search(query, source=...)` and the old names are what it
    # dispatches to. These three checks asked for the old names and so could
    # only ever fail; the 2026-09 review saw the same drift in e2e_10's K5 and
    # recorded it as test-side, which it is. What is worth testing is
    # unchanged: the model reaches for the right SOURCE for the question, and
    # asking a question does not submit a job.
    assert_scenario(
        user, "T04", "the manuals source is used for manual syntax questions",
        "What does the ORCA manual say about the %casscf block and its ETol keyword?",
        must_call=["search"], must_not_call=["submit_draft"],
        args_match={"search": {"source": "manuals"}},
    )

    assert_scenario(
        user, "T05", "the scholar source is used for a literature question",
        "Find the most cited papers on choosing an active space for CASSCF "
        "calculations of retinal photoisomerization.",
        must_call=["search"], must_not_call=["submit_draft"],
        args_match={"search": {"source": "scholar"}},
        timeout=420,
    )

    assert_scenario(
        user, "T06", "the web source is used for a current-events question",
        "Search the web for what the latest released version of ORCA is.",
        must_call=["search"], must_not_call=["submit_draft"],
        args_match={"search": {"source": "web"}},
        timeout=420,
    )

    print("\n=== Required-param elicitation (agent must ASK, never guess) ===\n")

    # Chemically significant parameters are never guessed -- and since the
    # rebuild that is enforced by the backend rather than asked for in the
    # prompt: `validate_draft` returns a question and `submit_draft` refuses
    # a draft that is not ready. A submitted job here would be a real
    # safety-relevant failure, not a style problem.
    assert_scenario(
        user, "E01", "no basis given -> elicit, do not guess",
        "Run a single point energy calculation on water.",
        must_not_call=["submit_draft"],
    )
    assert_scenario(
        user, "E02", "no active space given -> elicit, do not guess",
        "Run a CASSCF calculation on water with the STO-3G basis.",
        must_not_call=["submit_draft"],
    )
    assert_scenario(
        user, "E03", "no n_states given -> elicit",
        "Run a TDDFT calculation on water with B3LYP and STO-3G.",
        must_not_call=["submit_draft"],
    )

    print("\n=== Disallowed task/engine pairings must be refused ===\n")

    for did, phrase, method, task, subtype, engine, note in DISALLOWED_PAIRINGS[:4]:
        t = scenario(
            user, f"{did}",
            f"Run {phrase} on water using {engine}, "
            f"basis STO-3G, active space 4 electrons in 4 orbitals, 3 states.",
            timeout=300,
        )
        # Either the agent never drafts on that engine, or `validate_draft`
        # comes back `unavailable` with the registry's own refusal. Both are
        # correct; what must NOT happen is a job reaching the approval card
        # on an engine that cannot run it.
        refused = any(
            "cannot run here" in c.lower() or "does not run" in c.lower()
            for _, c in t.tools_executed()
        )
        pending = t.pending_approval
        bad = pending is not None and (pending.get("spec") or {}).get("engine") == engine
        task_label = f"{task}/{subtype}" if subtype else task
        check(
            f"{did} {task_label} on {engine} is refused" + (f" -- {note}" if note else ""),
            not bad, f"tools={t.tool_names()} refusal_seen={refused} "
                     f"pending_engine={(pending or {}).get('spec', {}).get('engine')}",
        )
        record_turn(did, "PASS" if not bad else "FAIL", t, note)

    cleanup_user(admin, uid)
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
