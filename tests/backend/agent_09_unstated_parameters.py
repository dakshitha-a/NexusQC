"""A value nobody said is marked as such on the approval card.

Fourteen required parameters carry "ONLY set this when the user has said..."
in their help, because a wrong value for any of them runs a different
calculation from the one that was asked for and looks identical to a stated
one on the approval card. `docs/BACKLOG.md` recorded what that sentence is
worth after a repeat probe: 2 of 3. A prompt cannot guard against the model
not following the prompt.

The guard is therefore not an attempt to stop the value being written. It is
that the card stops showing a guess and a choice the same way. Three
categories now: stated, defaulted by the app, and -- new -- present but
traceable to nothing anyone said.

The assertions that matter most here are the ones about NOT flagging. A
warning that fires on ordinary use stops being read, and then it is worse
than no warning at all, so grounding counts anything said anywhere in the
conversation including tool output: a basis from an earlier job's summary, an
active space from a literature search, a number given three turns ago.

Needs nothing running: no stack, no model, no Postgres.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_09_unstated_parameters.py
"""
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from app.agent.grounding import GUARDED_PARAMS, ungrounded_params  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


def said(*texts):
    return [HumanMessage(content=t) for t in texts]


check("the guarded set is the parameters whose help forbids inventing them",
      len(GUARDED_PARAMS) == 14 and "coordinate" in GUARDED_PARAMS
      and "basis" in GUARDED_PARAMS,
      "%d parameters" % len(GUARDED_PARAMS))

# --- what the user actually stated is never flagged ------------------------
msgs = said("run casscf(12,9) on water with cc-pVDZ and 2 excited states")
check("an active space the user gave is not flagged",
      ungrounded_params({"active_electrons": 12, "active_orbitals": 9}, msgs) == [])
check("a basis the user gave is not flagged, however they punctuated it",
      ungrounded_params({"basis": "cc-pvdz"}, msgs) == [],
      "cc-pVDZ, ccpvdz and 'cc pvdz' are the same answer")
check("a state count the user gave is not flagged",
      ungrounded_params({"n_excited_states": 2}, msgs) == [])

# --- what nobody said is flagged ------------------------------------------
flagged = ungrounded_params(
    {"n_points": 7, "coordinate": {"type": "bond", "atoms": [3, 4]}}, msgs)
check("a scan coordinate nobody named is flagged", "coordinate" in flagged, str(flagged))
check("a point count nobody gave is flagged", "n_points" in flagged, str(flagged))

# --- the false positives that would make this noise ------------------------
from_tool = [
    HumanMessage(content="use the same basis as that job"),
    ToolMessage(content="Job abc123 completed. basis=def2-tzvp, functional=pbe0",
                name="check_job_status", tool_call_id="x"),
]
check("a value taken from a tool's own output is not flagged",
      ungrounded_params({"basis": "def2-tzvp"}, from_tool) == [],
      "an earlier job's summary is where 'the same basis as that job' comes from")

recommended = [
    HumanMessage(content="what active space should I use?"),
    ToolMessage(content="AutoCAS recommends 8 electrons in 7 orbitals for this system.",
                name="search_active_space_literature", tool_call_id="y"),
]
check("an active space a literature search returned is not flagged",
      ungrounded_params({"active_electrons": 8, "active_orbitals": 7}, recommended) == [],
      "flagging the app's own recommendation would be crying wolf")

earlier = said("scan the O-H bond between atoms 1 and 2", "actually make it 12 points")
check("a value given several turns ago is still grounded",
      ungrounded_params({"coordinate": {"type": "bond", "atoms": [1, 2]}, "n_points": 12},
                        earlier) == [])

check("a boolean is never flagged",
      ungrounded_params({"preopt": True}, msgs) == [],
      "'true' is not a thing anyone types, and a wrong boolean is a coin flip, not an invention")

check("an unguarded parameter is ignored even when nobody said it",
      ungrounded_params({"use_tda": True, "weights": [0.5, 0.5]}, msgs) == [],
      "those are the app's to default, and applied_defaults already covers them")

check("with no conversation at all nothing is flagged",
      ungrounded_params({"n_points": 7}, []) == [],
      "an empty haystack proves nothing, and guessing there would flag everything")

# --- a number must be its own token ---------------------------------------
narrow = said("run this in cc-pVDZ")
check("a digit inside another token does not ground a number",
      "n_points" in ungrounded_params({"n_points": 2}, narrow),
      "the 2 in cc-pVDZ is not the user asking for 2 points")

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
