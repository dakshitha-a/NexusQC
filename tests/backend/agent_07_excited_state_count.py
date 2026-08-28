"""Asking for N excited states gets N excited states, whatever the method.

The bug this closes: "calculate 2 excited states with casscf(12,9)/cc-pvdz"
submitted `n_states=2`, and for a multireference method that counts
state-averaged roots INCLUDING the ground state -- so it computed S0 and S1.
One excited state. The user got half of what they asked for, the approval card
faithfully showed the number they had themselves said, and when the results
came back the agent described the job as defective for "only reporting one
excitation energy". It was not defective; it was asked the wrong question.

`n_states` was documented in three places at once -- the ParamSpec's help, its
`ask`, and two opposing warn_when entries -- and the model still got it wrong.
docs/BACKLOG.md already carried the general form of that lesson: a parameter
whose wrong value is silently plausible wants a structural guard, not a
probabilistic one.

So the model now answers `n_excited_states`, which means the same thing for
every method, and `n_states` is derived. These assertions are about the
derivation, because that is the part that can no longer be got wrong.

Needs nothing running: no stack, no model, no Postgres.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_07_excited_state_count.py
"""
import sys

from app.chemistry.registry2.elicitation import validate_draft  # noqa: E402
from app.chemistry.registry2.params import PARAMS_BY_NAME  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


WATER = {"identifier": "water", "name": "water", "smiles": "O", "charge": 0,
         "multiplicity": 1, "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.96], [0.93, 0.0, -0.24]],
         "source": "test"}


def draft(method, engine, n_excited, **extra):
    """The verdict's own draft, not the dict passed in.

    normalize_draft copies, so validate_draft's normalization -- including the
    derivation under test -- lands on the verdict, which is what every real
    caller reads.
    """
    d = {"task": "single_point", "subtype": "ee", "method": method, "engine": engine,
         "molecule": dict(WATER),
         "params": {"basis": "cc-pvdz", "n_excited_states": n_excited, **extra}}
    return validate_draft(d).draft


# --- the parameter the model is asked for has one meaning ------------------
check("the ambiguous n_states parameter is no longer model-facing",
      "n_states" not in PARAMS_BY_NAME and "n_excited_states" in PARAMS_BY_NAME,
      "it counted roots for one method family and excited states for the other")

spec = PARAMS_BY_NAME["n_excited_states"]
check("its help does not tell the model to count the ground state",
      "INCLUDES the ground state" not in spec.help,
      "that sentence is what produced a two-root CASSCF for a two-excited-state request")

# --- the derivation --------------------------------------------------------
cas = draft("casscf", "bagel", 2, active_electrons=12, active_orbitals=9)
check("CASSCF: 2 excited states becomes a 3-root state average",
      cas["params"]["n_states"] == 3,
      "this is the exact request that used to run S0+S1 and report one excitation")
check("CASSCF: the count the user gave is still on the draft",
      cas["params"]["n_excited_states"] == 2,
      "the card shows both, so the conversion is visible rather than done in the model's head")

pt2 = draft("caspt2", "bagel", 2, active_electrons=12, active_orbitals=9)
check("CASPT2 derives the same way", pt2["params"]["n_states"] == 3)

for method, engine in (("dft", "pyscf"), ("eom_ccsd", "pyscf"), ("hf", "orca")):
    d = draft(method, engine, 2, **({"functional": "b3lyp"} if method == "dft" else {}))
    check("%s: 2 excited states stays 2 roots" % method,
          d["params"]["n_states"] == 2,
          "a single-reference method computes its ground state separately")

one = draft("casscf", "bagel", 1, active_electrons=4, active_orbitals=4)
check("CASSCF: 1 excited state is a 2-root average", one["params"]["n_states"] == 2)

# --- a scan is promoted on the same unambiguous count ----------------------
#
# Promotion happens well after the molecule check, so the molecule goes in via
# `state` the way the graph supplies it, and the engine is one that actually
# runs pes_1d (BAGEL does not).
def scan_draft(n_excited):
    d = {"task": "pes_1d", "subtype": "", "method": "casscf", "engine": "pyscf",
         "params": {"basis": "sto-3g", "n_excited_states": n_excited,
                    "active_electrons": 4, "active_orbitals": 4,
                    "coordinate": {"type": "bond", "atoms": [1, 2]},
                    "scan_range": [0.9, 1.2], "n_points": 4}}
    return validate_draft(d, {"molecule": dict(WATER)}, check_external=False).draft


scan = scan_draft(2)
check("a CASSCF scan asking for excited states is promoted to an excited-state scan",
      scan["subtype"] == "ee",
      "one threshold serves both method families now, because the count means one thing")
check("and the promoted scan carries the derived root count",
      scan["params"].get("n_states") == 3)

ground_scan = scan_draft(0)
check("zero excited states stays a ground-state scan",
      ground_scan["subtype"] != "ee",
      "and derives n_states=1, the ordinary single-root CASSCF")
check("its derived root count is 1", ground_scan["params"].get("n_states") == 1)

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
