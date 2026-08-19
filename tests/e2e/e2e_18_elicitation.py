"""The elicitation conversation, end to end, against a served model.

`tests/backend/elic_01_draft_scenarios.py` proves `validate_draft` decides
correctly, and `agent_02_draft_flow.py` proves the tools built on it
behave. Neither involves a model. This script is the part that only a real
conversation can show: that the agent **relays the backend's question
rather than composing its own**, and that answering it in ordinary English
advances the draft.

That distinction is the whole design. The backend can return a perfect
question and the run is still a failure if the model paraphrases it into
something vaguer, answers it from its own guess, or asks for three things
at once. So the assertion here is on the *text the user would see*: the
question's own wording has to appear in the assistant's reply.

What is deliberately NOT asserted is that the model reaches the answer in
a fixed number of turns, or via a fixed tool sequence. Those are the model's
to vary; the contract is the question's wording and the fact that nothing
runs until the draft is ready.

Sequence assertions come from the parameter table itself rather than being
copied here, so a reworded `ParamSpec.ask` cannot leave this script
asserting text that no longer exists anywhere.

Run:  bash tests/e2e/run_e2e.sh e2e_18
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record_turn  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.chemistry.registry2.params import PARAMS_BY_NAME  # noqa: E402


def ask_text(param: str) -> str:
    """The registry's own question for one parameter."""
    return PARAMS_BY_NAME[param].ask


def _distinctive_words(question: str) -> list[str]:
    """The words of a question that a paraphrase would not keep.

    The clause after a "--" or inside a parenthetical, which is where the
    parameter tables put the concrete part -- the example basis names, the
    CASSCF-vs-TDDFT distinction -- and the first thing a model drops when
    it rewrites a question in its own voice.
    """
    parts = [p.strip(" ?(.)") for p in question.replace("(", "--").split("--")]
    clause = max(parts, key=len)
    return [w.strip(",;.") for w in clause.lower().split() if len(w.strip(",;.")) >= 4]


def relayed(turn, question: str) -> tuple[bool, str]:
    """Did the backend's question reach the user in the backend's words?

    Token containment rather than substring matching: the model is free to
    bold it, bullet it, or put a sentence in front, and any of those breaks
    a contiguous match while leaving the question perfectly intact. What it
    is NOT free to do is reword it, which drops these tokens.
    """
    words = _distinctive_words(question)
    text = said(turn)
    missing = [w for w in words if w not in text]
    ok = len(missing) <= max(1, len(words) // 5)
    return ok, f"missing {missing} from: {text[:250]}"


def said(turn) -> str:
    return (turn.assistant_text() or "").lower()


def main() -> None:
    admin = admin_client()
    tok = mint_invite(admin, "user")
    user, info = register(tok)
    uid = (info.get("user") or info).get("id")

    print("=== A draft is built one relayed question at a time ===\n")

    session = AgentSession.new(user, label="E18 elicitation")
    try:
        # 1. A bare request. The molecule is named, nothing else is.
        t1 = session.say("Run a CASSCF calculation on water.", timeout=420)
        check("E18-01 the agent starts a draft rather than guessing",
              "start_job_draft" in t1.tool_names(),
              f"tools={t1.tool_names()}")
        check("E18-02 and submits nothing", "submit_draft" not in t1.tool_names(),
              f"tools={t1.tool_names()}")
        record_turn("E18-01", "PASS" if "start_job_draft" in t1.tool_names() else "FAIL", t1)

        ok, detail = relayed(t1, ask_text("basis"))
        check("E18-03 the basis question reaches the user in the registry's words",
              ok, detail)

        # 2. Answer it in ordinary English, not as a parameter name.
        t2 = session.say("Use STO-3G.", timeout=420)
        check("E18-04 the answer is recorded through update_job_draft",
              "update_job_draft" in t2.tool_names(), f"tools={t2.tool_names()}")
        check("E18-05 still nothing submitted",
              "submit_draft" not in t2.tool_names(), f"tools={t2.tool_names()}")

        # CASSCF needs an active space, and it is never assumed -- the whole
        # point of the parameter table having no default for it.
        ok, detail = relayed(t2, ask_text("active_electrons"))
        check("E18-06 the active-space question is asked, not assumed", ok, detail)

        # 3. Answer both halves of the active space at once. The backend asks
        #    one at a time; a user answering ahead must not be re-asked.
        t3 = session.say("Four electrons in four orbitals.", timeout=420)
        asked_again, _ = relayed(t3, ask_text("active_electrons"))
        check("E18-07 answering ahead is accepted, not re-asked",
              not asked_again, f"re-asked: {said(t3)[:300]}")

        # 4. Finish it and let the card appear.
        t4 = session.say("Two states, please. Go ahead and run it.", timeout=600)
        pending = t4.pending_approval or session.state().get("pending_approval")
        check("E18-08 the completed draft reaches an approval card",
              pending is not None,
              f"tools={t4.tool_names()}")
        if pending:
            spec = pending.get("spec") or {}
            check("E18-09 the card carries the v2 task",
                  pending.get("task") == "single_point",
                  f"task={pending.get('task')!r}/{pending.get('subtype')!r}")
            check("E18-10 at the level of theory that was asked for",
                  (spec.get("params") or {}).get("method") == "casscf"
                  or spec.get("method") == "casscf",
                  f"spec={spec.get('method')!r} params={spec.get('params')}")
            check("E18-11 with the active space the user gave, not a guess",
                  (spec.get("params") or {}).get("active_electrons") == 4
                  and (spec.get("params") or {}).get("active_orbitals") == 4,
                  f"params={spec.get('params')}")
            check("E18-12 and the basis the user gave",
                  str((spec.get("params") or {}).get("basis", "")).lower() == "sto-3g",
                  f"params={spec.get('params')}")
            check("E18-13 the card shows the input that would run",
                  bool(pending.get("input_preview")), "input_preview was empty")
        record_turn("E18-08", "PASS" if pending else "FAIL", t4)
    finally:
        session.close()

    print("\n=== A combination no engine here can run is explained, not attempted ===\n")

    s2 = AgentSession.new(user, label="E18 unavailable")
    try:
        t = s2.say("Run a CASPT2 single point on water with PySCF, sto-3g, "
                   "four electrons in four orbitals.", timeout=420)
        check("E18-14 nothing reaches an approval card",
              (t.pending_approval or s2.state().get("pending_approval")) is None,
              "a card appeared for a combination that cannot run")
        # BAGEL is the only CASPT2 engine here, and the refusal says so
        # rather than silently rerouting -- which would answer a different
        # question than the one asked.
        check("E18-15 and the alternative engine is named",
              "bagel" in said(t), f"reply was: {said(t)[:300]}")
        record_turn("E18-14", "PASS", t)
    finally:
        s2.close()

    cleanup_user(admin, uid)
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
