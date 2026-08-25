"""Checks that a BAGEL job reusing another job's orbitals keeps its own geometry.

    conda activate qc-agent
    PYTHONPATH=$PWD python3 scripts/validate_bagel_orbital_reuse.py

BAGEL's reference archive stores the geometry alongside the orbitals, and
`load_ref` restores both unless told otherwise. Without
`"continue_geom": false` the calculation quietly runs on the SOURCE job's
structure instead of the one in its own molecule block. It still converges,
still reports results, and still writes a complete summary; the numbers are
just for a different geometry than the user asked about. No amount of running
the job catches that, which is why it is asserted on the input instead.

Only the input is built here, so nothing needs BAGEL installed and the whole
script runs in well under a second.
"""
import sys

from app.chemistry.jobs import bagel_runner

WATER = {"symbols": ["O", "H", "H"],
         "coords": [[0, 0, 0.117], [0, 0.755, -0.469], [0, -0.755, -0.469]],
         "charge": 0, "multiplicity": 1}

# Every job_type reachable with initial_orbitals_job_id set, spelled the way
# the run_* functions actually spell it when they call _build_input. The
# parameter is gated to multireference methods on the _CAS_TASKS set (see
# registry2/params.py), and those tasks resolve into exactly these branches.
#
# The second element is a block the branch must emit. That is not decoration:
# _build_input takes job_type as a plain string and falls through to a generic
# CASSCF assembly for anything it does not recognise, so an invented name like
# "freq" or "nacme" (both wrong, both tried during development) still produces
# a load_ref block with continue_geom set and still passes every check that
# only looks at load_ref. Asserting on the wrapper is what makes a misspelled
# job_type fail instead of quietly testing the same branch seven times.
#
# mo_visualization is absent deliberately: it is not in _CAS_TASKS, so it can
# never carry initial_orbitals_job_id, and its branch emits no preamble.
REUSE_CAPABLE = [
    ("casscf", "casscf"),
    ("caspt2", "smith"),
    ("geometry_optimization", "optimize"),
    ("opt_freq", "hessian"),
    ("frequency", "hessian"),
    ("gradient", "force"),
    ("nac", "nacme"),
]

BASE = {"basis": "cc-pvdz", "active_electrons": 4, "active_orbitals": 4,
        "n_states": 2, "method": "casscf"}

ok = True


def check(label, condition, detail=""):
    global ok
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    ok = ok and condition


for job_type, required_block in REUSE_CAPABLE:
    params = dict(BASE, initial_orbitals_job_id="deadbeefcafe")
    if job_type == "nac":
        params["state_pairs"] = [[1, 2]]
    blocks = bagel_runner._build_input(WATER, params, job_type)[0]["bagel"]
    titles = [b.get("title") for b in blocks]
    load_ref = next((b for b in blocks if b.get("title") == "load_ref"), None)

    print(f"{job_type}:")
    check("a load_ref block is emitted", load_ref is not None)
    if load_ref is None:
        continue
    check("continue_geom is false", load_ref.get("continue_geom") is False, repr(load_ref))
    # false, not absent and not a string: BAGEL's JSON reader wants a real
    # boolean, and an absent key is the default this exists to override.
    check("the geometry to project onto comes first",
          "molecule" in titles and titles.index("molecule") < titles.index("load_ref"),
          " -> ".join(t for t in titles if t))
    # Reusing orbitals replaces the fresh guess rather than following it, so an
    # hf preamble alongside load_ref would mean the archive is being read and
    # then thrown away.
    check("no hf preamble competes with the archive", "hf" not in titles[:titles.index("load_ref")])
    check(f"this really is the {job_type} branch", required_block in titles,
          " -> ".join(t for t in titles if t))

print("\nwithout a source job, nothing changes:")
plain = bagel_runner._build_input(WATER, dict(BASE), "casscf")[0]["bagel"]
plain_titles = [b.get("title") for b in plain]
check("no load_ref block", "load_ref" not in plain_titles)
check("an hf preamble instead", "hf" in plain_titles, " -> ".join(t for t in plain_titles if t))

print("\nRESULT:", "all checks passed" if ok else "FAILURES above")
sys.exit(0 if ok else 1)
