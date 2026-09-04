"""The refinement reads the specification it was pointed at.

Every `cas_reco` job writes `active_space_spec.json`, and until this step
nothing read it: `spec.rebuild_in_basis` had no caller anywhere under `app/`.
So the portable handoff ran in one direction only. The recommendation wrote
down the question it had asked -- the oriented targets in the minimal reference
basis, the projection threshold, the tier it selected -- and the refinement,
whose entire premise is "refine THAT space", re-derived the question from
scratch against whatever the constants happened to be at the moment it ran.

Four things are asserted here, and they are four different failures.

**The handoff happens, and says so.** A refinement pointed at a recommendation
reports the source job, that the specification was used, and which tier that
job selected. `spec_used` is the load-bearing field: without it a fallback
reads exactly like a successful handoff, since both carry a source job id.

**A mismatch raises rather than falling back.** A missing artifact is not an
error -- recommendations written before the specification existed have none --
but a specification for a different structure is not a missing artifact, it is
a positive statement that the space being refined does not describe this
molecule. Falling back there would produce a job reporting that it refined a
recommendation it does not derive from.

**The fallback is never silent.** No source job, or an unreadable one, leaves a
named note on the result saying the space was re-derived here.

**The rebuild does not cry wolf on a narrowed specification.** This one is a
consequence of the prerequisite fix rather than of the feature. `spec.build`
took `tier="recommended"` as a default that NEITHER runner overrode, so every
specification ever written claimed the pool tier even when the pointer had
moved to `state-narrowed`. Passing `tier=rec.recommended` fixes it and creates
a trap in the same motion: `rebuild_in_basis` reproduces the POOL, so comparing
its result against a narrowed `selected_tier` would report "gives CAS(22e,14o)
where it recorded CAS(14e,10o)" on every narrowed specification, forever, as a
false alarm about a basis dependence that is really the narrowing working. The
comparison is against the pool tier, and the difference from the selected tier
is explained rather than flagged.
"""
import os
import shutil
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

from app.config import JOBS_DIR                                  # noqa: E402
from app.chemistry.cas import spec as spec_mod                   # noqa: E402
from app.chemistry.jobs import pyscf_runner                      # noqa: E402
from scripts.casbench import reference_data as ref               # noqa: E402

PASS = 0
FAIL = 0

# Every job directory this script makes, so it deletes exactly what it created
# and nothing else. These are real directories under data/jobs -- the loader
# resolves a sibling job's artifact through JOBS_DIR, the same convention
# `_seed_initial_orbitals` uses, so a temp directory would not be found.
CREATED = []


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))


def molecule_of(name, displace=None):
    syms, co, chg, mult = ref.molecule(name)
    coords = [[float(x) for x in c] for c in co]
    if displace is not None:
        atom, axis, amount = displace
        coords[atom][axis] += amount
    return {"name": name, "symbols": list(syms), "coords": coords,
            "charge": int(chg), "multiplicity": int(mult)}


def new_job_dir():
    job_id = f"castest{uuid.uuid4().hex[:8]}"
    path = os.path.join(str(JOBS_DIR), job_id)
    os.makedirs(path, exist_ok=True)
    CREATED.append(path)
    return job_id, path


def main():
    print("A recommendation on water, written where a sibling job can find it")
    src_id, src_dir = new_job_dir()
    rec_summary = pyscf_runner.run_cas_recommendation(
        molecule_of("water"),
        {"n_states": 1, "_job_dir": src_dir,
         "verify_active_space": False})["summary"]
    spec_path = os.path.join(src_dir, "active_space_spec.json")
    check("the recommendation wrote an active_space_spec.json",
          os.path.exists(spec_path))
    with open(spec_path) as fh:
        written = spec_mod.ActiveSpaceSpec.from_json(fh.read())
    check(f"and its selected_tier is the tier the job selected, "
          f"{rec_summary['recommended_tier']!r}",
          written.selected_tier == rec_summary["recommended_tier"],
          f"spec says {written.selected_tier!r}, job says "
          f"{rec_summary['recommended_tier']!r}")

    print("\nA refinement pointed at it reads it")
    _rid, ref_dir = new_job_dir()
    s = pyscf_runner.run_cas_refinement(
        molecule_of("water"),
        {"n_states": 1, "_job_dir": ref_dir,
         "active_space_source_job_id": src_id})["summary"]
    check("the summary names the source job",
          s.get("active_space_source_job_id") == src_id,
          f"got {s.get('active_space_source_job_id')!r}")
    check("and records that the specification was actually used, rather than "
          "leaving a fallback indistinguishable from a handoff",
          s.get("spec_used") is True, f"spec_used {s.get('spec_used')!r}")
    check(f"and carries the tier that source job selected "
          f"({s.get('source_selected_tier')!r})",
          s.get("source_selected_tier") == written.selected_tier,
          f"got {s.get('source_selected_tier')!r}")
    check("and its recorded size is the one in the specification",
          s.get("source_selected_space") == list(written.space()),
          f"got {s.get('source_selected_space')} vs {list(written.space())}")
    fell_back = [n for n in s.get("notes", []) if "re-derived here" in n]
    check("with no fallback note, because nothing fell back",
          not fell_back, f"notes {fell_back}")

    print("\nThe same specification applied to a geometry that has moved")
    _rid, moved_dir = new_job_dir()
    try:
        pyscf_runner.run_cas_refinement(
            # 0.5 A is ten times the specification's 0.05 A tolerance, which is
            # deliberately loose enough to survive a coordinate round trip.
            molecule_of("water", displace=(1, 0, 0.5)),
            {"n_states": 1, "_job_dir": moved_dir,
             "active_space_source_job_id": src_id})
        check("a refinement on a moved geometry is refused", False,
              "it ran and returned a result")
    except ValueError as exc:
        check(f"a refinement on a moved geometry is refused: "
              f"{str(exc)[:60]}...", "moved" in str(exc), str(exc)[:200])

    print("\nAnd to a different molecule entirely")
    _rid, other_dir = new_job_dir()
    try:
        pyscf_runner.run_cas_refinement(
            molecule_of("formaldehyde"),
            {"n_states": 1, "_job_dir": other_dir,
             "active_space_source_job_id": src_id})
        check("a refinement on a different molecule is refused", False,
              "it ran and returned a result")
    except ValueError as exc:
        check(f"a refinement on a different molecule is refused: "
              f"{str(exc)[:60]}...",
              "does not transfer" in str(exc) or "different" in str(exc),
              str(exc)[:200])

    print("\nNo source job at all: the old behaviour, but not in silence")
    _rid, bare_dir = new_job_dir()
    s2 = pyscf_runner.run_cas_refinement(
        molecule_of("water"), {"n_states": 1, "_job_dir": bare_dir})["summary"]
    check("it still runs and returns a refined space",
          s2.get("recommended_active_orbitals", 0) > 0,
          f"got {s2.get('recommended_active_orbitals')!r}")
    check("spec_used is false", s2.get("spec_used") is False,
          f"got {s2.get('spec_used')!r}")
    said = [n for n in s2.get("notes", [])
            if "No source recommendation was named" in n]
    check("and a note says the space was re-derived here", bool(said),
          f"notes {s2.get('notes')}")

    print("\nA source job whose specification is missing")
    absent_id, absent_dir = new_job_dir()          # made, but left empty
    _rid, af_dir = new_job_dir()
    s3 = pyscf_runner.run_cas_refinement(
        molecule_of("water"),
        {"n_states": 1, "_job_dir": af_dir,
         "active_space_source_job_id": absent_id})["summary"]
    check("a missing artifact falls back rather than failing",
          s3.get("spec_used") is False, f"got {s3.get('spec_used')!r}")
    said = [n for n in s3.get("notes", [])
            if "no active_space_spec.json" in n and absent_id in n]
    check("and the note names the job whose specification was missing",
          bool(said), f"notes {s3.get('notes')}")

    print("\nThe specification records the question this recommendation asked")
    # Water is the case, and it is why this is asserted on water rather than on
    # the pyrrole cas_09 uses. `recommend` builds from the pi and lone-pair
    # targets normally, but falls back to the sigma framework when that space
    # comes out completely full -- which is every molecule with no pi system.
    # Both runners wrote the VALENCE perception into the specification
    # unconditionally, so water's recorded two targets rebuilding to CAS(4e,2o)
    # -- the space `recommend` had just rejected in a note as describing no
    # correlation -- beside a tier table recording the CAS(8e,6o) it actually
    # recommended. Nothing raised, and cas_09 could not see it: pyrrole has a
    # pi system, so for pyrrole the two perceptions agree.
    from pyscf import gto, scf                                   # noqa: E402
    syms, co, _c, _m = ref.molecule("water")
    m = gto.M(atom=[(s, tuple(c)) for s, c in zip(syms, co)],
              basis="def2-svp", verbose=0)
    mf = scf.RHF(m).density_fit()
    mf.kernel()
    ncas, nelecas, _mo, _cas, notes = spec_mod.rebuild_in_basis(mf, written)
    recommended = (rec_summary["recommended_active_electrons"],
                   rec_summary["recommended_active_orbitals"])
    check(f"water's specification rebuilds to the space it recommended, "
          f"CAS{recommended}, and not to the lone-pair-only CAS(4e, 2o) it "
          f"rejected",
          (sum(nelecas), ncas) == recommended,
          f"rebuilt ({sum(nelecas)},{ncas}), recommended {recommended}")
    check("so the rebuild reports no disagreement with what was recorded",
          not [n for n in notes if "where it recorded" in n], f"notes {notes}")

    print("\nThe rebuild does not cry wolf on a narrowed specification")
    # Built by hand rather than by running uracil at three states, which is the
    # molecule this case exists for and is minutes of CASSCF away. What is
    # under test is the comparison `rebuild_in_basis` makes, not the narrowing
    # that produces the tier, and cas_13 already covers the narrowing.
    narrowed = spec_mod.ActiveSpaceSpec.from_json(written.to_json())
    pool = narrowed.tiers["recommended"]
    narrowed.tiers["state-narrowed"] = {
        "n_electrons": pool["n_electrons"] - 2,
        "n_orbitals": pool["n_orbitals"] - 1}
    narrowed.selected_tier = "state-narrowed"
    ncas, nelecas, _mo, _cas, notes = spec_mod.rebuild_in_basis(mf, narrowed)
    check(f"the rebuild reproduces the pool, CAS({sum(nelecas)}e, {ncas}o), "
          f"which is what a specification can carry",
          (sum(nelecas), ncas) == (pool["n_electrons"], pool["n_orbitals"]),
          f"got ({sum(nelecas)},{ncas}) vs "
          f"({pool['n_electrons']},{pool['n_orbitals']})")
    wolf = [n for n in notes if "where it recorded" in n]
    check("and does NOT report the narrowing as a size disagreement",
          not wolf, f"false alarm: {wolf}")
    explained = [n for n in notes if "re-derived rather than rebuilt" in n]
    check("but does say the selected tier is built on top of what it rebuilt",
          bool(explained), f"notes {notes}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        # Delete exactly the job directories this script created. Nothing here
        # goes through the job manager, so there is nothing else to clean up
        # and nothing of anyone else's to sweep.
        for path in CREATED:
            shutil.rmtree(path, ignore_errors=True)
        print(f"cleaned up {len(CREATED)} job directories this script created")
    raise SystemExit(code)
