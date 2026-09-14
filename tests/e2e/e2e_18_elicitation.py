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
        # 1. "Run a CASSCF calculation on water" names a level of theory and
        #    leaves the calculation implicit, which is how people talk. The
        #    backend keeps the method and asks the question that is actually
        #    open -- it does not infer that a CASSCF must be a single point,
        #    because it could equally be an optimization or a spectrum.
        t1 = session.say("Run a CASSCF calculation on water.", timeout=420)
        check("E18-01 the agent starts a draft rather than guessing",
              "start_job_draft" in t1.tool_names(),
              f"tools={t1.tool_names()}")
        check("E18-02 and submits nothing", "submit_draft" not in t1.tool_names(),
              f"tools={t1.tool_names()}")
        record_turn("E18-01", "PASS" if "start_job_draft" in t1.tool_names() else "FAIL", t1)

        check("E18-03 a method given where a task was expected is not rejected",
              "don't recognize" not in said(t1) and "not a calculation" not in said(t1),
              f"reply: {said(t1)[:250]}")
        check("E18-04 and the open question -- which calculation -- is put to the user",
              "what kind of calculation" in said(t1),
              f"reply: {said(t1)[:250]}")

        # 2. Name the calculation. Now the parameter questions begin.
        t2 = session.say("A single point energy, please.", timeout=420)
        ok, detail = relayed(t2, ask_text("basis"))
        check("E18-05 the basis question reaches the user in the registry's words",
              ok, detail)
        check("E18-06 still nothing submitted",
              "submit_draft" not in t2.tool_names(), f"tools={t2.tool_names()}")

        # 3. Answer it in ordinary English, not as a parameter name.
        t3 = session.say("Use STO-3G.", timeout=420)
        check("E18-07 the answer is recorded through update_job_draft",
              "update_job_draft" in t3.tool_names(), f"tools={t3.tool_names()}")
        # CASSCF needs an active space, and it is never assumed -- the whole
        # point of the parameter table having no default for it.
        ok, detail = relayed(t3, ask_text("active_electrons"))
        check("E18-08 the active-space question is asked, not assumed", ok, detail)

        # 4. Answer both halves at once. The backend asks one at a time; a
        #    user answering ahead must not be asked the same thing again.
        t4 = session.say("Four electrons in four orbitals.", timeout=420)
        asked_again, _ = relayed(t4, ask_text("active_electrons"))
        check("E18-09 answering ahead is accepted, not re-asked",
              not asked_again, f"re-asked: {said(t4)[:250]}")

        # 5. The card, which since R-101 may already be up.
        #
        # Answering the last open question completes the draft, and a complete
        # draft raises its own approval card in that same turn. So by the time
        # step 4 returns there is usually nothing left to say, and saying "go
        # ahead and run it" anyway is now REFUSED with a 409: posting a message
        # while a card is pending would discard the card (R-038), which is the
        # gap that refusal exists to close. This script crashed on that 409 at
        # the 2026-09 gate, with both mechanisms working exactly as designed
        # and neither of them wrong.
        #
        # So: ask for the card first, and only prompt if the app has genuinely
        # not raised one. Elicitation ending at a card without a further
        # instruction is the behaviour under test, not a shortcut around it.
        pending = t4.pending_approval or session.state().get("pending_approval")
        carded_on_the_answer = pending is not None
        if not carded_on_the_answer:
            t5 = session.say("Go ahead and run it.", timeout=600)
            pending = t5.pending_approval or session.state().get("pending_approval")
            tools_note = f"tools={t5.tool_names()} (needed an explicit go-ahead)"
        else:
            tools_note = (f"tools={t4.tool_names()} (the card came up on the answer "
                          f"itself, which is R-101)")
        check("E18-10 the completed draft reaches an approval card",
              pending is not None, tools_note)
        if pending:
            spec = pending.get("spec") or {}
            params = spec.get("params") or {}
            check("E18-11 the card carries the v2 task",
                  pending.get("task") == "single_point",
                  f"task={pending.get('task')!r}/{pending.get('subtype')!r}")
            check("E18-12 at the level of theory that was asked for",
                  params.get("method") == "casscf" or spec.get("method") == "casscf",
                  f"runner={spec.get('method')!r} params={params}")
            check("E18-13 with the active space the user gave, not a guess",
                  params.get("active_electrons") == 4 and params.get("active_orbitals") == 4,
                  f"params={params}")
            check("E18-14 and the basis the user gave",
                  str(params.get("basis", "")).lower() == "sto-3g", f"params={params}")
            check("E18-15 the card shows the input that would run",
                  bool(pending.get("input_preview")),
                  f"input_preview length={len(pending.get('input_preview') or '')}")
        record_turn("E18-10", "PASS" if pending else "FAIL",
                    t5 if not carded_on_the_answer else t4)
    finally:
        session.close()

    print("\n=== A combination no engine here can run is explained, not attempted ===\n")

    s2 = AgentSession.new(user, label="E18 unavailable")
    try:
        t = s2.say("Run a CASPT2 single point on water with PySCF, sto-3g, "
                   "four electrons in four orbitals.", timeout=420)
        card = t.pending_approval or s2.state().get("pending_approval")
        check("E18-16 nothing reaches an approval card",
              card is None,
              f"pending={(card or {}).get('task')!r} -- a card must not appear for a "
              f"combination no engine here can run")
        # BAGEL is the only CASPT2 engine here, and the refusal says so
        # rather than silently rerouting -- which would answer a different
        # question than the one asked.
        check("E18-17 and the alternative engine is named",
              "bagel" in said(t), f"reply: {said(t)[:300]}")
        record_turn("E18-16", "PASS" if card is None else "FAIL", t)
    finally:
        s2.close()

    cleanup_user(admin, uid)
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
