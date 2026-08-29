"""Every bound tool actually runs when called. A smoke test, deliberately.

This exists because `explain_active_space` shipped raising `NameError: name
'n_states' is not defined` on every single call, and nothing caught it: it
compiled, it imported, its schema was valid, the token-budget test counted it
happily, and the agent suites never exercised that particular tool. The bug
came from a scripted edit whose anchor line appeared in TWO functions, so the
replacement landed in the wrong one and left the other referencing a name
nobody assigned.

The lesson is not about that one tool. A tool is reachable only when the model
chooses it, so a tool nothing routinely exercises can be broken for a long time
while every other check stays green. This calls each one with plausible
arguments and asserts only that it returns rather than raising -- what it
returns is that tool's own test's business.

A refusal IS a pass here. Most of these tools refuse cleanly when the state is
empty ("No molecule is set", "No jobs have been submitted yet"), and that is
the behaviour this repo wants; what must never happen is an exception reaching
the graph.

Needs nothing running: no stack, no model, no Postgres. Tools that would make
a network call are skipped by name and listed, so the skip is visible rather
than silent.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_08_tools_are_callable.py
"""
import sys

from app.agent.tools import STATIC_TOOLS  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


WATER = {"name": "water", "identifier": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.96], [0.93, 0.0, -0.24]]}
STATE = {"molecule": WATER, "active_job_ids": [], "job_draft": {}}

# Plausible arguments per tool. Anything not listed is called with no arguments
# beyond the injected state, which is itself a real code path (every tool has
# to cope with being called before the user has said much).
ARGS = {
    "set_geometry": {"identifier": "water"},
    "lookup_capabilities": {"task": "single point"},
    "search_active_space_literature": {"n_excited_states": 2, "basis": "cc-pvdz"},
    "explain_active_space": {"active_electrons": 6, "active_orbitals": 6,
                             "n_excited_states": 2, "basis": "cc-pvdz"},
    "start_job_draft": {"task": "single point"},
    "update_job_draft": {"updates": {"basis": "cc-pvdz"}},
    "submit_draft": {},
    "check_job_status": {},
    "plot": {"kind": "uvvis"},
    "geometry_parameters": {"parameters": [{"type": "bond", "atoms": [1, 2]}]},
    "list_ensemble_geometries_in_window": {"job_id": "nosuchjob1234"},
    "convert_energy_units": {"values": [5.1], "from_units": "eV", "to_units": "hartree"},
    "search": {"query": "cc-pVDZ basis", "source": "manuals"},
    "resolve_basis_from_bse": {"basis_query": "cc-pvdz"},
}

# These reach the network. Skipped by name so the skip is visible in the output
# rather than being a silent gap of the kind this test exists to close.
NETWORK = set()

names = [t.name for t in STATIC_TOOLS]
print("%d bound tools: %s\n" % (len(names), ", ".join(names)))

unspecified = [n for n in names if n not in ARGS]
check("every bound tool has arguments here", not unspecified,
      "unlisted: %s -- add them, or this test silently stops covering them" % unspecified)

for tool in STATIC_TOOLS:
    if tool.name in NETWORK:
        print("[SKIP] %s (network)" % tool.name)
        continue
    kwargs = dict(ARGS.get(tool.name) or {})
    fn = tool.func
    varnames = fn.__code__.co_varnames[:fn.__code__.co_argcount]
    if "state" in varnames:
        kwargs["state"] = dict(STATE)
    if "tool_call_id" in varnames:
        kwargs["tool_call_id"] = "call_smoke"
    try:
        out = fn(**kwargs)
        check("%s runs" % tool.name, out is not None,
              "returned %s" % type(out).__name__)
    except Exception as e:  # noqa: BLE001 -- the whole point is to catch any
        check("%s runs" % tool.name, False, "%s: %s" % (type(e).__name__, e))

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
