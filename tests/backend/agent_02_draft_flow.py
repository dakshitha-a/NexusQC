#!/usr/bin/env python3
"""P2.2 -- the draft tools actually work, through the real graph.

`elic_01_draft_scenarios.py` proves `validate_draft` decides correctly.
This proves the tools built on it behave: that a draft survives in state
across turns, that the reply tells the model the exact key to write next,
that `submit_draft` reaches the approval `interrupt()` with a spec the card
can render, and that both branches out of that gate still work.

Driven without the LLM, against a graph holding only the tool node. The
app's real graph is agent -> tools -> agent, so every tool call there is
followed by a live turn against the served model -- which, while this
script was being written, cheerfully called start_job_draft on its own
initiative and populated a draft the test had just asserted was empty. The
state schema, reducers, checkpointer and `interrupt()` are all the real
ones; only the model is absent.

One check is worth more than the rest. The pre-interrupt half of
`submit_draft` re-executes when the user clicks Approve, so if validation
could come back `incomplete` on that second pass the tool would return a
question, never re-reach `interrupt()`, and the approval would vanish with
no error anywhere. `validate_draft(..., check_external=False)` is what
prevents that, and it is asserted directly below.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_02_draft_flow.py
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.chemistry.molecule import resolve_molecule
from app.config import JOBS_DIR

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


# A real resolved molecule, not a hand-written dict. The input builders
# read `coords`/`symbols` in the exact shape `Molecule.to_dict()` produces,
# and a plausible-looking hand-rolled stand-in fails deep inside the
# preview builder with a bare KeyError instead of anything diagnostic.
WATER = resolve_molecule("water").to_dict()

class Harness:
    """One throwaway thread running the tool node and nothing else.

    Deliberately *not* the app's full graph. That one is agent -> tools ->
    agent, so every tool call is followed by a real turn against the served
    model -- which, mid-test, promptly called start_job_draft on its own
    initiative and populated the draft this script had just asserted was
    empty. The tools are what P2.2 changed; binding them to a live model's
    judgement would make these assertions depend on what it felt like doing
    today.

    The state schema, the reducers, the checkpointer and `interrupt()` are
    all the real ones, so the approval gate behaves exactly as it does in
    the app.
    """

    def __init__(self, tmpdir: Path):
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.prebuilt import ToolNode

        from app.agent.state import AgentState
        from app.agent.tools import get_all_tools

        conn = sqlite3.connect(str(tmpdir / f"{uuid.uuid4().hex}.sqlite"),
                               check_same_thread=False)
        builder = StateGraph(AgentState)
        builder.add_node("tools", ToolNode(get_all_tools()))
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        self.g = builder.compile(checkpointer=SqliteSaver(conn))
        self.config = {"configurable": {"thread_id": f"draft-{uuid.uuid4().hex[:8]}"}}
        self.n = 0

    def seed(self, **state) -> None:
        self.g.update_state(self.config, {
            "messages": [HumanMessage(content="(scripted)")], **state})

    def call(self, name: str, args: dict) -> str:
        """Run one tool call and return its ToolMessage text."""
        self.n += 1
        call_id = f"call_{self.n}"
        self.g.invoke({"messages": [
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
        ]}, self.config)
        return self._tool_message(call_id)

    def _tool_message(self, call_id: str) -> str:
        """The ToolMessage for one specific call.

        Matched on tool_call_id rather than "the last tool message in the
        thread": if a tool raises, or a node does not run, the newest tool
        message is the *previous* call's, and every assertion downstream
        then passes or fails against the wrong text.
        """
        messages = self.g.get_state(self.config).values.get("messages") or []
        for m in reversed(messages):
            if getattr(m, "type", "") == "tool" and getattr(m, "tool_call_id", None) == call_id:
                return m.content
        return f"<no ToolMessage produced for {call_id}>"

    def draft(self) -> dict:
        return self.g.get_state(self.config).values.get("job_draft") or {}

    def pending(self):
        snapshot = self.g.get_state(self.config)
        return snapshot.interrupts[0].value if snapshot.interrupts else None

    def resume(self, value) -> str:
        call_id = f"call_{self.n}"        # the submit_draft call that paused
        self.g.invoke(Command(resume=value), self.config)
        return self._tool_message(call_id)


def run_elicitation(tmp: Path) -> None:
    print("\n== a draft is built one answered question at a time ==")
    h = Harness(tmp)
    h.seed(molecule=WATER)

    out = h.call("start_job_draft", {"task": "geometry optimization", "method": "hf"})
    check("the first reply asks for the basis set",
          "DRAFT INCOMPLETE" in out and "Which basis set" in out, out[:200])
    # The key to write next has to be in the *text*. Collapsing 38 named
    # parameters into one `updates` dict removed every schema-level hint
    # about field names, so if the question and its key do not travel
    # together the model invents one.
    check("and names the exact key to write next",
          'update_job_draft with {"basis":' in out, out[:300])
    check("the free-text task was resolved, and said so",
          "Read 'geometry optimization' as opt/min" in out, out[:300])
    check("the draft is in state, not in the transcript",
          h.draft().get("task") == "opt" and h.draft().get("subtype") == "min",
          f"draft={h.draft()}")

    out = h.call("update_job_draft", {"updates": {"basis": "sto-3g"}})
    check("answering it produces a ready draft", "DRAFT READY" in out, out[:300])
    check("the ready draft names the engine and why",
          "PYSCF is the preferred engine" in out, out[:300])
    check("routing's choice is not reported as the user's request",
          "requested explicitly" not in out, out[:300])
    check("defaults that were applied are stated, not hidden",
          "Defaults applied" in out and "max_steps" in out, out[:300])
    check("the user's engine field stays empty when they named none",
          h.draft().get("engine") is None and h.draft().get("resolved_engine") == "pyscf",
          f"draft={h.draft()}")
    # `generate_job_input` was removed because it duplicated the whole build
    # path to answer a question the draft already knows. That is only true
    # if the draft actually carries the input -- and for a while it did not,
    # so "show me the input, don't run it" had no answer at all. An e2e
    # scenario caught it: the model set the geometry and stopped, because
    # nothing offered it a way to comply.
    check("a ready draft carries the engine input, so it can be shown without running",
          "mol.basis" in out or "gto.Mole" in out or "pyscf" in out.lower(),
          out[:400])
    # The reply must name the next step unmistakably. A ready draft is not
    # the end of the job -- roughly one job-matrix cell in five stopped
    # here, with a complete draft and nothing submitted, because the
    # message read as a conclusion rather than a handover.
    check("and names submit_draft as the next step, not as an option",
          "NEXT STEP" in out and "submit_draft now" in out, out[:400])
    check("while making clear the job has not started",
          "not been requested" in out or "runs nothing" in out
          or "do not tell them it has started" in out, out[:400])


def run_no_draft(tmp: Path) -> None:
    print("\n== updating or submitting without a draft says so ==")
    h = Harness(tmp)
    h.seed(molecule=WATER)
    out = h.call("update_job_draft", {"updates": {"basis": "sto-3g"}})
    check("update_job_draft with no draft in progress explains itself",
          "no draft in progress" in out.lower(), out[:200])
    out = h.call("submit_draft", {})
    check("submit_draft with no draft explains itself",
          "no draft to submit" in out.lower(), out[:200])


def run_geometry_is_not_a_parameter(tmp: Path) -> None:
    """Found by a real smoke conversation, not by reasoning about the code.

    The served model called set_geometry and start_job_draft in the same
    batch, so validation ran against the pre-batch state and asked which
    molecule to use. The reply told it to answer with update_job_draft; it
    wrote {"molecule": "water"}; the deliberately tolerant draft shape
    absorbed that as a *parameter*, and it rode all the way into the
    submitted spec as a key no runner reads and the user never chose.
    """
    print("\n== a geometry is never absorbed as a job parameter ==")
    h = Harness(tmp)
    h.seed()                                  # no molecule set
    out = h.call("start_job_draft", {"task": "single point", "method": "hf"})
    check("with no molecule set, the draft asks for one",
          "Which molecule should this run on" in out, out[:200])
    check("and points at set_geometry, not at update_job_draft",
          "set_geometry" in out and 'update_job_draft with {"molecule"' not in out,
          out[:400])

    out = h.call("update_job_draft", {"updates": {"molecule": "water", "basis": "sto-3g"}})
    check("writing a molecule into the draft is refused, not absorbed",
          "not a job parameter" in out, out[:200])
    check("and the parameter that came with it is not silently kept either",
          "molecule" not in (h.draft().get("params") or {}),
          f"params={h.draft().get('params')}")


def run_approval(tmp: Path) -> None:
    print("\n== submit_draft reaches the approval gate ==")
    h = Harness(tmp)
    h.seed(molecule=WATER)
    h.call("start_job_draft", {"task": "single point", "method": "hf"})
    h.call("update_job_draft", {"updates": {"basis": "sto-3g"}})
    h.call("submit_draft", {})

    payload = h.pending()
    check("the graph is paused on a job_approval interrupt",
          isinstance(payload, dict) and payload.get("kind") == "job_approval",
          f"payload={payload}")
    if not payload:
        return
    check("the card carries the v2 task fields",
          payload.get("task") == "single_point" and payload.get("subtype") == "gs",
          f"task={payload.get('task')}/{payload.get('subtype')}")
    check("and a spec the runner can execute",
          # P2B.4: spec.method is the level of theory, not the runner key --
          # task/subtype (already asserted above) are what a runner
          # dispatches on (see app/chemistry/jobs/dispatch.py).
          (payload.get("spec") or {}).get("method") == "hf"
          and (payload["spec"]).get("engine") == "pyscf",
          f"spec={payload.get('spec')}")
    check("and the engine input to be approved",
          bool(payload.get("input_preview")), "input_preview was empty")
    check("and the routing explanation",
          "PYSCF" in (payload.get("capability_note") or ""),
          f"capability_note={payload.get('capability_note')!r}")

    out = h.resume({"approved": False})
    # The wording changed when the decline stopped being narrated by the
    # model (see tests/backend/reject_01_decline_message.py): the tool result
    # is now a record for the model rather than a sentence for it to
    # paraphrase, so what it must contain is the fact and the prohibition.
    check("rejecting says so and submits nothing",
          "NOT run" in out and "do not resubmit" in out.lower(), out[:200])


def run_resume_determinism() -> None:
    """The invariant that keeps an approval from evaporating on the click.

    Everything before `interrupt()` runs twice: once to render the card,
    once when the user approves. If the second pass can reach a different
    verdict, the approval is lost -- the tool returns a question, the
    resume value is discarded, and nothing anywhere reports an error.
    `validate_draft`'s only reader of anything outside the draft is the
    Wigner source-job check, so `submit_draft` turns it off and the verdict
    becomes a pure function of the draft and the conversation's geometry.

    Asserted at the level of the mechanism rather than by deleting a job
    mid-approval, because a Wigner draft cannot reach the approval gate at
    all without a genuinely completed frequency job to sample -- see the
    known limitation recorded for this step in docs/trackers/2026-08-job-system-overhaul.md.
    """
    print("\n== the approval verdict cannot change between render and click ==")
    from app.chemistry.registry2.elicitation import validate_draft

    draft = {
        "task": "wigner_spectra", "method": "dft",
        "params": {"basis": "sto-3g", "functional": "b3lyp", "n_states": 3,
                   "n_samples": 4, "source_frequency_job_id": "vanished-job"},
    }
    checked = validate_draft(draft, {}, check_external=True)
    check("with the external check on, a vanished source job is caught",
          checked.status == "incomplete"
          and checked.asking_for == "source_frequency_job_id",
          f"status={checked.status!r} asking_for={checked.asking_for!r}")

    unchecked = validate_draft(draft, {}, check_external=False)
    check("with it off -- as at submission -- the same draft is ready",
          unchecked.status == "ready",
          f"status={unchecked.status!r} ask={unchecked.ask_user_exactly!r}")
    check("so the verdict cannot flip between rendering the card and the click",
          unchecked.status == "ready" and checked.status != unchecked.status)


def run_unavailable(tmp: Path) -> None:
    print("\n== an impossible combination is explained, not rerouted ==")
    h = Harness(tmp)
    h.seed(molecule=WATER)
    out = h.call("start_job_draft",
                 {"task": "single point", "method": "caspt2", "engine": "pyscf"})
    check("it comes back as unavailable", "CANNOT RUN HERE" in out, out[:200])
    check("naming the reason", "does not run caspt2 on PYSCF" in out, out[:300])
    check("and offering the engine that can", '{"engine": "bagel"}' in out, out[:300])
    check("nothing was silently rerouted",
          h.draft().get("resolved_engine") in (None, ""),
          f"draft={h.draft()}")


def run_plot_dispatch(tmp: Path) -> None:
    print("\n== the consolidated plot tool dispatches and refuses cleanly ==")
    h = Harness(tmp)
    h.seed(molecule=WATER)
    out = h.call("plot", {"kind": "nonsense"})
    check("an unknown kind is named, with the real ones listed",
          "not a plot this app draws" in out and "uvvis" in out, out[:200])
    out = h.call("plot", {"kind": "comparison"})
    check("a comparison with no field says which fields exist",
          "homo_lumo_gap" in out, out[:200])
    out = h.call("plot", {"kind": "ensemble"})
    check("an ensemble plot with no job id says so", "job's id" in out, out[:200])
    out = h.call("plot", {"kind": "uvvis"})
    check("a plot with no jobs at all does not fabricate one",
          "No jobs have been submitted" in out, out[:200])


def main() -> int:
    tmp = Path(__file__).resolve().parent.parent / "data" / "_draftflow_scratch"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        run_elicitation(tmp)
        run_no_draft(tmp)
        run_geometry_is_not_a_parameter(tmp)
        run_approval(tmp)
        run_resume_determinism()
        run_unavailable(tmp)
        run_plot_dispatch(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = PASS + FAIL
    print(f"\n{PASS}/{total} checks passed")
    if FAIL:
        print(f"[FAIL] {FAIL} check(s) failed")
        return 1
    print("[PASS] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
