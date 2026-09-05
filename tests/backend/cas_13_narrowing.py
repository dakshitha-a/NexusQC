"""The quick recommendation narrows to what the requested states actually use.

The narrowing was written for the refinement loop and was reachable only from
there, so a user who asked for a quick recommendation on uracil with three
states was quoted CAS(22e,14o) while the space those three states use is ten
orbitals, and only a refinement costing minutes would find that out. Nothing
about the rule needs a CASSCF: it wants a geometry, the projection, and the
linear-response analysis of the requested states, all of which the quick path
already has by the time it reports.

This drives `run_cas_recommendation` rather than the library, because the
wiring is what was missing and the library was already correct.

Four things are asserted, and the last two are about not breaking what was
there. Uracil must reach its literature space. A molecule whose space is
already right must not move. The headline numbers must follow the tier pointer,
which they did not at first: `ne, no` are read off the recommendation before the
states are analysed, so the summary reported the pool's size under the narrowed
tier's name. And the projector's own pool must still be offered under its own
name, since `Tier` and `Recommendation.to_dict` feed the job summary, the
frontend, `active_space_spec.json` and the capability matrix.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

from app.chemistry.jobs import pyscf_runner                      # noqa: E402
from scripts.casbench import reference_data as ref               # noqa: E402

PASS = 0
FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))


def recommend(name, n_states, basis=None):
    syms, co, chg, mult = ref.molecule(name)
    molecule = {"name": name, "symbols": list(syms),
                "coords": [[float(x) for x in c] for c in co],
                "charge": int(chg), "multiplicity": int(mult)}
    params = {"n_states": n_states, "_job_dir": tempfile.mkdtemp(),
              "verify_active_space": False}
    if basis:
        params["basis"] = basis
    return pyscf_runner.run_cas_recommendation(molecule, params)["summary"]


def space_of(summary):
    return (summary["recommended_active_electrons"],
            summary["recommended_active_orbitals"])


def main():
    print("Uracil, three states: the case the narrowing exists for")
    s = recommend("uracil", 3)
    tiers = s["active_space_tiers"]
    lit = ref.REFERENCE_SPACES["uracil"][0]
    check(f"the recommended tier is the narrowed one (got "
          f"{s['recommended_tier']!r})",
          s["recommended_tier"] == "state-narrowed")
    check(f"and it is uracil's literature space {lit}, which the quick tier "
          f"never reached before", space_of(s) == tuple(lit),
          f"got {space_of(s)}")
    # (18,12), not the (22,14) this asserted until 2026-09-04. The pool lost
    # two orbitals and four electrons when the planar three-coordinate lone
    # pair was withdrawn: uracil has two amide nitrogens, each planar and
    # three-coordinate, each of which was being handed an in-plane lone-pair
    # target it has no lone pair to fill. What this check is FOR is unchanged
    # and still holds -- the projector's own pool keeps its own name when the
    # pointer moves to the narrowed tier, because Tier and
    # Recommendation.to_dict feed the summary, the frontend,
    # active_space_spec.json and the capability matrix.
    check("the projector's own pool is still offered under its own name",
          "recommended" in tiers and
          (tiers["recommended"]["n_electrons"],
           tiers["recommended"]["n_orbitals"]) == (18, 12),
          f"got {tiers.get('recommended')}")
    narrowed = tiers["state-narrowed"]
    check("the headline follows the tier pointer rather than the pool",
          space_of(s) == (narrowed["n_electrons"], narrowed["n_orbitals"]),
          f"headline {space_of(s)} vs tier "
          f"({narrowed['n_electrons']},{narrowed['n_orbitals']})")
    # The bar was a factor of four and is a factor of two, and the reason is
    # not that narrowing got worse. The narrowed tier is unchanged at (14,10)
    # and 4,950 CSFs; what shrank is the POOL it is measured against, from
    # 41,405 CSFs to 15,730, because two of the orbitals the saving used to be
    # counted over were the spurious amide lone pairs and should never have
    # been in the pool to save. A real 3.2x saving over an honest pool is
    # worth more than an 8.4x saving over an inflated one.
    #
    # Two rather than three, so this is a statement about narrowing being
    # substantial rather than a constant fitted to today's number.
    pool_csf = tiers["recommended"]["feasibility"]["n_csf"]
    check(f"and it is very much cheaper: {narrowed['feasibility']['n_csf']:,} "
          f"CSFs against {pool_csf:,}",
          narrowed["feasibility"]["n_csf"] < pool_csf / 2)

    print("\nPyrrole, three states: its literature space was a tier away")
    s = recommend("pyrrole", 3)
    check(f"reaches (6,5) as the recommendation rather than only as the "
          f"minimal tier (got {space_of(s)})", space_of(s) == (6, 5))

    print("\nFormaldehyde, three states: already right, must not move")
    s = recommend("formaldehyde", 3)
    check(f"stays at its literature (6,4) (got {space_of(s)})",
          space_of(s) == (6, 4))
    check("and no narrowed tier is invented when there is nothing to narrow",
          "state-narrowed" not in s["active_space_tiers"],
          f"tiers {list(s['active_space_tiers'])}")

    print("\nA ground-state request has no states to narrow against")
    s = recommend("uracil", 1)
    check("no narrowing without requested states",
          s["recommended_tier"] != "state-narrowed",
          f"tier {s['recommended_tier']}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
