#!/usr/bin/env python3
"""A Wigner distribution is marked with the geometry it was sampled around.

A geometry-parameter histogram shows how far an ensemble's structures
spread and, until now, said nothing about what they spread FROM. The first
thing a reader asks of one is "where was the equilibrium?", and that was
the one value not on the plot.

The whole correctness of the feature is which geometry the red line comes
from, and it is not obvious: an `opt_freq` source's `spec.molecule` is the
PRE-optimization input, while `summary.optimized_molecule` is the minimum
its normal modes were actually computed at. Drawing the first would produce
a line that looks authoritative and sits in the wrong place -- and nothing
downstream would catch it, which is exactly why this test computes the
expected value from the source job's own optimized geometry independently
and requires the two to differ from the input geometry's value.

Not the first sample either: a Wigner ensemble displaces every sample,
sample 1 included, so it is no closer to the equilibrium than any other.

Runs inside the api container. The histogram needs only `ensemble_xyz`,
which is written when the ensemble is submitted rather than when its
samples finish, so this seeds and reads back without waiting for any
excited-state calculation to run.

    python3 tests/backend/wig_02_equilibrium_marker.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}" + (f" -- {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


IN_CONTAINER = r'''
import json, math, time
from app.agent import tools as T
from app.chemistry.jobs import geometry_resolve
from app.chemistry.jobs.base import (
    JobSpec, get_job_manager, sub_job_ids_of, delete_job_dir,
)
from app.chemistry.jobs.wigner import sample_from_source_job
from app.plots import store as plot_store

# Deliberately NOT at its minimum: the O-H bonds start long, so the
# optimization moves them and the input geometry's bond length differs
# measurably from the optimized one. If the marker were taken from
# spec.molecule instead of summary.optimized_molecule, this test sees it.
STRETCHED_WATER = {"name": "water", "symbols": ["O", "H", "H"],
                   "coords": [[0.0, 0.0, 0.15], [0.0, 0.90, -0.60], [0.0, -0.90, -0.60]],
                   "charge": 0, "multiplicity": 1}

def bond(coords, i, j):
    a, b = coords[i - 1], coords[j - 1]
    return math.dist(a, b)

mgr = get_job_manager()
src_id = mgr.submit(JobSpec(task="opt_freq", subtype="", method="hf", engine="pyscf",
                            molecule=STRETCHED_WATER, params={"basis": "sto-3g"}))
deadline = time.time() + 420
while time.time() < deadline:
    if (mgr.status(src_id) or {}).get("status") in ("completed", "failed", "cancelled"):
        break
    time.sleep(1.0)

out = {"source_status": (mgr.status(src_id) or {}).get("status")}
src_result = mgr.result(src_id) or {}
src_summary = src_result.get("summary") or {}
optimized = src_summary.get("optimized_molecule") or {}
out["input_bond"] = bond(STRETCHED_WATER["coords"], 1, 2)
out["optimized_bond"] = bond(optimized.get("coords") or [[0,0,0]]*3, 1, 2)

# The rule itself, before anything is drawn with it.
resolved, err = geometry_resolve.equilibrium_geometry_of_source(
    {"task": "opt_freq", "molecule": STRETCHED_WATER}, src_result)
out["rule"] = {"error": err, "bond": bond((resolved or {}).get("coords") or [[0,0,0]]*3, 1, 2)}

# An ensemble around it. Its geometries are written at submission, so the
# histogram is readable immediately; the samples themselves need not run.
samples, diagnostics = sample_from_source_job(
    optimized, src_summary, n_samples=20, random_seed=1234,
    low_freq_cutoff_cm1=100.0, temperature_K=0.0,
)
master = JobSpec(task="wigner_spectra", subtype="", method="dft", engine="pyscf",
                 molecule=optimized,
                 params={"basis": "sto-3g", "functional": "b3lyp", "n_states": 3,
                         "n_samples": 20, "random_seed": 1234,
                         "source_frequency_job_id": src_id,
                         "want_oscillator_strengths": True})
master_id = mgr.submit_ensemble(master, samples, diagnostics)

out["ensemble_lookup"] = {}
eq, eq_err = geometry_resolve.equilibrium_geometry_for_ensemble(master_id)
out["ensemble_lookup"] = {"error": eq_err,
                          "bond": bond((eq or {}).get("coords") or [[0,0,0]]*3, 1, 2)}

state = {"owner_user_id": None, "active_job_ids": [master_id], "messages": []}
reply = T._geometry_parameters_histogram(
    master_id, "wigner_spectra", [{"type": "bond", "atoms": [1, 2]},
                                  {"type": "angle", "atoms": [2, 1, 3]}], state)
out["reply"] = reply
plot_ids = []
if "plot id is " in reply or "plot_id=" in reply:
    import re
    m = re.search(r"plot_id=(\S+) version=(\S+)", reply)
    if m:
        plot_ids.append(m.group(1))
        path = plot_store.version_path(None, m.group(1), m.group(2))
        out["png_bytes"] = Path(str(path)).stat().st_size if path else 0

# A batch has no single geometry to be "around", so it gets no line.
batch_reply = T._geometry_parameters_histogram(
    master_id, "batch", [{"type": "bond", "atoms": [1, 2]}], state)
out["batch_reply_has_equilibrium"] = "red dashed line" in batch_reply

for pid in plot_ids:
    plot_store.delete_plot(None, pid)
for jid in [*sub_job_ids_of(master_id), master_id, src_id]:
    try:
        mgr.cancel(jid)
    except Exception:
        pass
    try:
        delete_job_dir(jid)
    except Exception as e:
        out.setdefault("cleanup_errors", []).append(f"{jid}: {e}")

print("RESULT_JSON " + json.dumps(out))
'''


def main() -> int:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c",
         "from pathlib import Path\n" + IN_CONTAINER],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
    if line is None:
        print(proc.stdout[-2000:])
        print(proc.stderr[-3000:], file=sys.stderr)
        check("the container run produced a result", False, "no RESULT_JSON line")
        return 1
    r = json.loads(line[len("RESULT_JSON "):])
    if r.get("cleanup_errors"):
        print(f"  (cleanup) {r['cleanup_errors']}")

    print("== the source job ==")
    check("the opt_freq source completed", r["source_status"] == "completed", str(r["source_status"]))
    moved = abs(r["input_bond"] - r["optimized_bond"])
    check("its optimization really moved the geometry, so the two candidates differ",
          moved > 0.01, f"input {r['input_bond']:.4f} A vs optimized {r['optimized_bond']:.4f} A")

    print("\n== which geometry the rule picks ==")
    rule = r["rule"]
    check("for an opt_freq source it is the OPTIMIZED geometry, not the input",
          rule["error"] is None and abs(rule["bond"] - r["optimized_bond"]) < 1e-9,
          json.dumps(rule))
    check("...which is the one its normal modes were computed at",
          abs(rule["bond"] - r["input_bond"]) > 0.01,
          f"picked {rule['bond']:.4f} A, input was {r['input_bond']:.4f} A")

    look = r["ensemble_lookup"]
    check("an ensemble finds it through its own recorded source job",
          look["error"] is None and abs(look["bond"] - r["optimized_bond"]) < 1e-9,
          json.dumps(look))

    print("\n== the plot ==")
    reply = r["reply"]
    check("the histogram is drawn", "plot_id=" in reply, reply[:160])
    check("the reply names the line and what it is",
          "red dashed line" in reply and "normal modes were computed at" in reply,
          reply[:200])
    expected = f"{r['optimized_bond']:.3f}".rstrip("0").rstrip(".")
    check("the value quoted is the optimized geometry's own, formatted as on the plot",
          f"bond(1,2) {expected}," in reply or f"bond(1,2) {expected} " in reply,
          f"looking for 'bond(1,2) {expected}' in: {reply[-260:]}")
    check("the image really rendered", r.get("png_bytes", 0) > 5000, str(r.get("png_bytes")))

    print("\n== a collection with no equilibrium gets no line ==")
    check("a batch histogram draws no equilibrium reference",
          r["batch_reply_has_equilibrium"] is False,
          "its children can start from unrelated structures")

    print(f"\n{PASS}/{PASS + FAIL} checks passed in this script.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
