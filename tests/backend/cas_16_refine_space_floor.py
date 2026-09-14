"""A refined active space never comes back with fewer than two orbitals.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \\
      PYTHONPATH=$PWD python3 tests/backend/cas_16_refine_space_floor.py

Found while settling R-099, which is why it is a separate script rather than a
line in `cas_14_refinement_drawer.spec.mjs`: the drawer renders whatever the
refinement publishes, and what needed fixing was what the refinement was
willing to publish.

WHAT WENT WRONG
---------------
`app/chemistry/cas/refine.py` prunes orbitals that carry no correlation, and
guards each prune by asking whether the space that would be left still holds a
meaningfully occupied orbital and a meaningfully empty one. Both tests run on
the natural occupations of the CURRENT space, before the trial space is
re-solved, and that is the hole: a single kept orbital can look partially
occupied inside a six-orbital space and necessarily goes to 2.0000 once it is
the only orbital left.

Asking for two states on water produced exactly that. The quick space was six
orbitals, one prune took it to one, and the job completed and published a
refined space of CAS(2,1) with a single natural occupation of 2.0000, a
character label of "pi", and a stop reason reading "pruning would leave no
correlated pair, so the space is left as it is". It had already left no
correlated pair. CAS(2,1) holds exactly one determinant whatever its occupation
is, so it is not a multireference space at all; a CASSCF on it recovers no
correlation and is a closed-shell reference written the long way. Anything
downstream that took that space at face value, a CASPT2 on top of it or a user
copying it into their own input, would be starting from a result that cannot
mean what it says.

The fix is a structural floor rather than another occupation test: a prune that
would leave fewer than two active orbitals is refused, and the space is left at
its previous size with a stop reason that says so.

WHAT THIS SCRIPT CHECKS
-----------------------
It seeds the same recommendation-then-refinement pair `cas_14` seeds, on water
with PySCF, but asks for two states rather than one, which is the case that
exposed this. Both jobs are driven to completion in ONE in-container process,
and the refinement's summary is read out of `result.json` rather than through
`JobManager.status()`, because status.json carries only status, message and
updated_at; reading the summary from the wrong place is how R-099 came to be
recorded as a missing-data defect in the first place.

Then, on the refined space it publishes:

  * at least two active orbitals, which is the floor itself
  * one natural occupation per active orbital, so the table the drawer draws
    describes the space the summary claims
  * at least one occupation meaningfully below 2, so the space holds something
    to correlate rather than merely having two orbitals in it

Both jobs are deleted afterwards whatever happens.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
N_STATES = 2
# An occupation below this is a hole worth correlating into. The refinement's
# own inert-orbital threshold is 1.98, and this is deliberately looser: the
# question here is whether the space has any correlation in it at all, not
# whether every orbital earns its place.
CORRELATED_BELOW = 1.99

PROBE = f'''
import json, os, time
from app.chemistry.jobs.base import JobSpec, get_job_manager, JOBS_DIR, delete_job_dir

mgr = get_job_manager()
WATER = {{"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}}


def wait(job_id, limit=900):
    end = time.time() + limit
    status = None
    while time.time() < end:
        status = (mgr.status(job_id) or {{}}).get("status")
        if status in ("completed", "failed", "cancelled"):
            return status
        time.sleep(1.0)
    return "timeout"


def summary_of(job_id):
    with open(os.path.join(str(JOBS_DIR), job_id, "result.json")) as fh:
        return json.load(fh).get("summary") or {{}}


rec = ref = None
try:
    rec = mgr.submit(JobSpec(task="cas_reco", subtype="", method="casscf", engine="pyscf",
                             molecule=WATER, params={{"n_states": {N_STATES}}}))
    rec_status = wait(rec)
    ref = mgr.submit(JobSpec(task="cas_reco", subtype="refine", method="casscf", engine="pyscf",
                             molecule=WATER,
                             params={{"n_states": {N_STATES}, "active_space_source_job_id": rec}}))
    ref_status = wait(ref)
    s = summary_of(ref) if ref_status == "completed" else {{}}
    print(json.dumps({{
        "rec": rec, "rec_status": rec_status,
        "ref": ref, "ref_status": ref_status,
        "electrons": s.get("recommended_active_electrons"),
        "orbitals": s.get("recommended_active_orbitals"),
        "occupations": s.get("natural_occupations"),
        "characters": s.get("orbital_characters"),
        "stopped_because": s.get("stopped_because"),
        "quick_orbitals": s.get("quick_active_orbitals"),
    }}))
finally:
    for jid in (rec, ref):
        if jid:
            try:
                delete_job_dir(jid)
            except Exception:
                pass
'''


def main() -> None:
    proc = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", PROBE],
                          cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=2400)
    if proc.returncode != 0:
        print(proc.stderr[-1500:], file=sys.stderr)
        raise RuntimeError("the in-container probe failed")
    r = json.loads(proc.stdout.strip().splitlines()[-1])

    print(f"recommendation {r['rec']}: {r['rec_status']}")
    print(f"refinement     {r['ref']}: {r['ref_status']}")
    print(f"quick space had {r['quick_orbitals']} orbitals; refined to "
          f"CAS({r['electrons']}, {r['orbitals']})")
    print(f"natural occupations: {r['occupations']}")
    print(f"orbital characters:  {r['characters']}")
    print(f"stopped because: {r['stopped_because']}")

    check("the recommendation completed", r["rec_status"] == "completed", r["rec_status"])
    check("the refinement completed", r["ref_status"] == "completed", r["ref_status"])

    orbitals = r.get("orbitals")
    check(
        "the refined active space has at least two orbitals, since one orbital holds a single "
        "determinant and is not a multireference space at all",
        isinstance(orbitals, int) and orbitals >= 2,
        f"refined to CAS({r.get('electrons')}, {orbitals}) with occupations {r.get('occupations')}",
    )

    occ = r.get("occupations") or []
    check(
        "there is one natural occupation per active orbital, so the table describes the space "
        "the summary claims",
        isinstance(orbitals, int) and len(occ) == orbitals,
        f"{len(occ)} occupations for {orbitals} orbitals",
    )
    check(
        f"at least one occupation is below {CORRELATED_BELOW}, so the space has something to "
        f"correlate rather than merely having two orbitals in it",
        any(float(x) < CORRELATED_BELOW for x in occ),
        f"occupations {occ}",
    )

    summary()


if __name__ == "__main__":
    main()
