"""P4.2, second half: the drift tolerance over the WHOLE refinement set.

`refine_constants.py` sweeps the refinement constants on a named subset of six
molecules, and its answer is that only uracil moves. That is a weak basis for
setting a global constant: five of the six cannot move at any setting, so the
grid is really an experiment on one molecule.

This asks the same question of every molecule that refines. It runs the full
refinement benchmark once with `MAX_ENERGY_DRIFT_EV` overridden, and the
caller compares the spaces against the committed `docs/casbench/refine.md`.
If the only row that moves is still uracil, the tolerance is unconstrained by
the rest of the set and cannot be chosen on this evidence.

Run:  PYTHONPATH=$PWD QC_CASBENCH_DRIFT_EV=0.10 \
        python3 -u scripts/casbench/drift_full_set.py
"""
import os
import sys

from app.chemistry.cas import refine

DEFAULT = refine.MAX_ENERGY_DRIFT_EV


def main() -> int:
    ev = os.environ.get("QC_CASBENCH_DRIFT_EV")
    if ev is None:
        print("Set QC_CASBENCH_DRIFT_EV to the tolerance to test, in eV. "
              f"The shipped value is {DEFAULT}.")
        return 2
    refine.MAX_ENERGY_DRIFT_EV = float(ev)
    print(f"MAX_ENERGY_DRIFT_EV {DEFAULT} -> {refine.MAX_ENERGY_DRIFT_EV}",
          flush=True)

    from scripts.casbench import run_bench
    run_bench.set_refine()

    print("\nCompare the spaces above against docs/casbench/refine.md. "
          "Any row that differs is a molecule the tolerance actually "
          "decides; if uracil is the only one, the constant stays put.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
