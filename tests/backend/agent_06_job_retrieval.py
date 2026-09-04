"""Job-data retrieval regression: the wrong answers, not the payload size.

This exists because of one measured conversation. Six uracil jobs, and the
question "add the absolute ground state energies to the table". The reply
reported "CASSCF (6e,6o)" and "CASPT2 (6e,6o)" and then reasoned at length
about why a small (6e,6o) active space behaves as it does. Both jobs were
CASSCF(12,9): `active_electrons: 12`, `active_orbitals: 9`, on disk, in the
spec the agent had itself submitted.

Nothing was broken in the engines or the parsers. The agent called
check_job_status four times in that turn; each reply was ~27,000 characters,
93-96% of it a 132-row orbital table; the conversation reached 147,620
estimated tokens against a 53,488-token budget; and `_trim_history` dropped
89 of 92 messages from the front, including the two results the agent had
just fetched. It answered from a hole and filled the hole with a number that
looked right.

So the assertions here are about the specific things that went wrong:

  1. one name per quantity, so a lookup cannot miss a value that is present
     under another engine's name
  2. HOMO/LUMO energies that are NULL rather than 0.0 when the export has no
     eigenvalue -- otherwise the app itself manufactures the same class of
     confident, baseless number
  3. state counts that cannot be read two ways
  4. per-excited-state arrays with one indexing convention
  5. the current turn's tool results are never silently lost

Needs nothing running: no stack, no model, no Postgres.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_06_job_retrieval.py
"""
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import (  # noqa: E402
    _OMITTED_RESULT_NOTICE, _current_turn_start, _history_token_budget, _message_tokens, _trim_history,
)
from app.agent.tools import _FieldPathError, _resolve_field_path  # noqa: E402
from app.chemistry.jobs.derivatives import coupling_entry, coupling_result  # noqa: E402
from app.chemistry.jobs.facts import canonicalize, frontier_orbitals  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


# --------------------------------------------------------------------------
# 1. One name per quantity.
#
# These are the five real shapes from the conversation, trimmed to the keys
# that mattered. Before the canonical vocabulary a ground-state energy lived
# under four different names and `casscf_energy_hartree` was written as null
# while the value sat in `state_energies_hartree[0]`.
# --------------------------------------------------------------------------
BAGEL_CASSCF = {
    "state_energies_hartree": [-412.57243848, -412.39914986],
    "excitation_energies_eV": [4.715423570854075],
    "casscf_energy_hartree": None,
    "active_electrons": 12,
    "active_orbitals": 9,
    "n_states": 2,
    "dominant_transitions": [None, "29->30 (0.86)"],
}
PYSCF_TDDFT = {
    "ground_state_energy_hartree": -414.67165370011037,
    "excitation_energies_eV": [5.10176071402066, 5.847494493977446],
    "dominant_transitions": ["28->30 (0.41)", "29->30 (0.43)"],
    "n_states": 2,
}
PYSCF_EOM = {"ground_state_ccsd_energy_hartree": -413.7394747955721,
             "excitation_energies_eV": [5.260567894843885, 5.860716157168313]}
PYSCF_OPT = {"final_energy_hartree": -414.6716537001061, "converged": True,
             "optimized_molecule": {"symbols": ["O"], "coords": [[0.0, 0.0, 0.0]]}}

cas = canonicalize(BAGEL_CASSCF, {"engine": "bagel"})
tddft = canonicalize(PYSCF_TDDFT, {"engine": "pyscf"})
eom = canonicalize(PYSCF_EOM, {"engine": "pyscf"})
opt = canonicalize(PYSCF_OPT, {"engine": "pyscf"})

check("CASSCF ground-state energy is recovered from state_energies_hartree[0]",
      cas["total_energy_hartree"] == -412.57243848,
      "was null under casscf_energy_hartree")
check("TDDFT, EOM-CCSD and opt all report total_energy_hartree",
      tddft["total_energy_hartree"] == -414.67165370011037
      and eom["total_energy_hartree"] == -413.7394747955721
      and opt["total_energy_hartree"] == -414.6716537001061)
check("the old per-engine energy names are gone",
      not any(k in cas or k in tddft or k in eom or k in opt for k in (
          "casscf_energy_hartree", "ground_state_energy_hartree",
          "ground_state_ccsd_energy_hartree", "final_energy_hartree", "energy_hartree")))
check("optimized_molecule is optimized_geometry",
      "optimized_geometry" in opt and "optimized_molecule" not in opt)
check("the active space survives canonicalization intact",
      (cas["active_electrons"], cas["active_orbitals"]) == (12, 9),
      "this is the number the failing reply got wrong")

# --------------------------------------------------------------------------
# 1b. One name, two shapes: a coupling job's oscillator strengths.
#
# `oscillator_strengths` is per EXCITED STATE on an excited-state job and per
# STATE PAIR on a coupling job (app/chemistry/jobs/derivatives.py), and
# canonicalize re-indexes the per-excited-state arrays so entry i describes
# state i+1. That alignment used to be unreachable for a coupling result,
# because it had no state ladder and `_state_counts` therefore derived no
# bounds. Giving a coupling its ladder -- which is the whole point, a
# coupling cannot be computed without solving for the states -- handed that
# code the two numbers it needed to do the wrong thing.
#
# Three states and three pairs is the case that bites: len(value) ==
# n_states_total == n_excited_states + 1 holds by coincidence, and a
# three-pair job came back with three couplings and two intensities that no
# longer lined up with them. This is the exact PySCF SA-CASSCF shape from
# the conversation that prompted the change.
# --------------------------------------------------------------------------
PYSCF_NAC = coupling_result(
    [coupling_entry(pair, [[0.1, 0.0, 0.0]]) for pair in ([1, 2], [1, 3], [2, 3])],
    [[1, 2], [1, 3], [2, 3]],
    state_energies_hartree=[-78.07515845, -77.72566287, -77.53186089],
)
nac = canonicalize(PYSCF_NAC, {"engine": "pyscf"})

check("a coupling's per-pair oscillator strengths are not re-indexed as per-state",
      len(nac["oscillator_strengths"]) == len(nac["couplings"]) == nac["n_pairs"] == 3,
      "three pairs must keep three entries; slicing leaves them mismatched with couplings")
check("a coupling still reports the state ladder it was computed from",
      nac["state_energies_hartree"] == [-78.07515845, -77.72566287, -77.53186089]
      and nac["n_states_total"] == 3)
check("PySCF prints no gap of its own, so every pair's gap is derived from that ladder",
      all(g is not None for g in nac["energy_gaps_eV"])
      and abs(nac["energy_gaps_eV"][0] + nac["energy_gaps_eV"][2]
              - nac["energy_gaps_eV"][1]) < 1e-9,
      "S0->S1 plus S1->S2 must equal S0->S2, which cannot hold if pairs were mismatched")

# --------------------------------------------------------------------------
# 2. Frontier energies are nullable.
#
# BAGEL's molden export writes energy_eV = 0.0 for every active-space
# orbital, because a multi-configurational active orbital has no
# single-particle Fock eigenvalue. The HOMO of a CASSCF job IS an active
# orbital, so the obvious derivation hands back 0.0 as if it were an energy.
# --------------------------------------------------------------------------
BAGEL_ACTIVE_TABLE = [
    {"index": 1, "spin": None, "energy_eV": -561.1, "occupancy": 2.0},
    {"index": 2, "spin": None, "energy_eV": 0.0, "occupancy": 1.94},
    {"index": 3, "spin": None, "energy_eV": 0.0, "occupancy": 0.06},
]
PYSCF_TABLE = [
    {"index": 28, "spin": None, "energy_eV": -9.7, "occupancy": 2.0},
    {"index": 29, "spin": None, "energy_eV": -8.408683727412626, "occupancy": 2.0},
    {"index": 30, "spin": None, "energy_eV": 0.1638150687465625, "occupancy": 0.0},
]

bagel_frontier = frontier_orbitals(BAGEL_ACTIVE_TABLE)
pyscf_frontier = frontier_orbitals(PYSCF_TABLE)

check("a BAGEL active-space HOMO energy is null, not 0.0",
      bagel_frontier["homo_energy_eV"] is None,
      "0.0 here is the app inventing the number, not reading one")
check("its gap is null too rather than a difference of two non-energies",
      bagel_frontier["homo_lumo_gap_eV"] is None)
check("but the index and occupancy are still reported",
      bagel_frontier["homo_index"] == 2)
check("the reason travels with the missing value",
      "frontier_energy_unavailable" in bagel_frontier)
check("a PySCF table still yields a real HOMO, LUMO and gap",
      pyscf_frontier["homo_index"] == 29
      and abs(pyscf_frontier["homo_energy_eV"] + 8.408683727412626) < 1e-9
      and abs(pyscf_frontier["homo_lumo_gap_eV"] - 8.572498796159188) < 1e-9)

# --------------------------------------------------------------------------
# 3 and 4. State counts and per-excited-state indexing.
#
# `n_states: 2` meant S0+S1 for CASSCF and S1+S2 for TDDFT. Reading it
# without knowing the method family is how a correct two-root CASSCF job got
# reported as defective for "only reporting one excitation energy".
# --------------------------------------------------------------------------
check("CASSCF n_states=2 reads as 2 total, 1 excited",
      (cas["n_states_total"], cas["n_excited_states"]) == (2, 1))
check("TDDFT n_states=2 reads as 3 total, 2 excited",
      (tddft["n_states_total"], tddft["n_excited_states"]) == (3, 2))
check("the ambiguous n_states key is gone",
      "n_states" not in cas and "n_states" not in tddft)
check("BAGEL's ground-state slot is stripped from dominant_transitions",
      cas["dominant_transitions"] == ["29->30 (0.86)"],
      "entry i describes state i+1, in every engine")
check("a flat PySCF dominant_transitions list is left alone",
      tddft["dominant_transitions"] == ["28->30 (0.41)", "29->30 (0.43)"])

# --------------------------------------------------------------------------
# Field paths: a window of a bulk array, so reading part of a 132-row table
# does not mean putting all of it in the context that reading it informs.
# --------------------------------------------------------------------------
_S = {"orbital_table": PYSCF_TABLE, "excitation_energies_eV": [1.0, 2.0]}
check("a slice returns the window", len(_resolve_field_path(_S, "orbital_table[0:2]")) == 2)
check("a slice past the end clamps rather than refusing",
      len(_resolve_field_path(_S, "orbital_table[1:99]")) == 2)
check("a plain index still works",
      _resolve_field_path(_S, "excitation_energies_eV[1]") == 2.0)
try:
    _resolve_field_path(_S, "not_there")
    check("an unknown field is refused", False)
except _FieldPathError as e:
    check("an unknown field is refused, naming what is there",
          "orbital_table" in str(e))

# --------------------------------------------------------------------------
# 5. The current turn's tool results are never silently lost.
#
# Reproduces the shape of the turn that failed: a user question, then one
# assistant message calling check_job_status four times, then four oversized
# results. Previously the front-drop loop ate the first two by position.
# --------------------------------------------------------------------------
FILLER = "Earlier discussion of the uracil excited states. " * 400


def turn(result_chars):
    msgs = []
    for i in range(30):
        msgs.append(HumanMessage(content=FILLER))
        msgs.append(AIMessage(content=FILLER))
    msgs.append(HumanMessage(content="Add the absolute ground state energies to the table"))
    calls = [{"name": "check_job_status", "args": {}, "id": "call_%d" % i} for i in range(4)]
    msgs.append(AIMessage(content="", tool_calls=calls))
    for i, c in enumerate(calls):
        msgs.append(ToolMessage(content="Job %d results. " % i + "x" * result_chars,
                                name="check_job_status", tool_call_id=c["id"]))
    return msgs, calls


msgs, calls = turn(60000)
check("the turn boundary is found at the user's question",
      _current_turn_start(msgs) == 60)

kept = _trim_history(msgs)
kept_ids = {getattr(m, "tool_call_id", None) for m in kept if isinstance(m, ToolMessage)}
check("every current-turn tool result is still represented",
      all(c["id"] in kept_ids for c in calls),
      "none may vanish; over budget they are blanked with a marker instead")

blanked = [m for m in kept if isinstance(m, ToolMessage) and m.content == _OMITTED_RESULT_NOTICE]
check("an over-budget turn blanks results with an explicit marker",
      len(blanked) > 0,
      "%d of 4 blanked, telling the model to re-fetch rather than guess" % len(blanked))

call_ids = {c.get("id") for m in kept for c in (getattr(m, "tool_calls", None) or [])}
orphans = [m for m in kept if isinstance(m, ToolMessage) and m.tool_call_id not in call_ids]
check("no ToolMessage is left without its calling AIMessage",
      not orphans, "an orphan is a 400 from the endpoint, not a shorter prompt")

# The same turn at the payload sizes the canonical vocabulary produces:
# ~1,800 characters instead of ~27,000. Nothing should need blanking at all.
small, small_calls = turn(1800)
kept_small = _trim_history(small)
blanked_small = [m for m in kept_small
                 if isinstance(m, ToolMessage) and m.content == _OMITTED_RESULT_NOTICE]
small_ids = {getattr(m, "tool_call_id", None) for m in kept_small if isinstance(m, ToolMessage)}
check("at realistic payload sizes nothing has to be blanked",
      not blanked_small and all(c["id"] in small_ids for c in small_calls),
      "budget %d, turn costs %d tokens" % (
          _history_token_budget(), sum(_message_tokens(m) for m in small[60:])))

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
