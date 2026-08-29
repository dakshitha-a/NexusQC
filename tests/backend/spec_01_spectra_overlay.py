#!/usr/bin/env python3
"""A spectrum travels with the job, and several can share one axis.

Before this a spectrum could be looked at and not worked with. The curve
existed as a PNG; what reached the model was the sticks (excitation
energies and oscillator strengths, frequencies and IR intensities) or, for
a pooled nuclear ensemble, nothing at all. So there was no way to quote a
peak and no way to put two methods' spectra on one axis.

The properties worth checking are the ones a code read cannot settle:

- everything the resolver returns peaks at exactly 1. The ensemble's own
  .dat file is already normalized and the two stick paths are normalized
  here to match; if they did not, an overlay mixing a Wigner spectrum with
  a TDDFT one would show the first at 1.0 and the second at raw
  oscillator-strength scale, which looks like a result rather than a units
  mistake.
- an overlay resamples every curve onto ONE grid. Each source builds its
  own from its own data range, so two methods' curves are not comparable
  point-for-point until they share one.
- the cached table each series is read back from reaches 1.0 too. A curve
  documented as normalized to its own peak and topping out at 0.996 reads
  as a result rather than as sampling.
- IR and UV/Vis are refused as a pair. Both axes are energy, but a
  vibrational band and an electronic transition on one scale is a picture
  of nothing.

Runs inside the api container: it seeds real excited-state jobs and reads
their results through the job manager.

    python3 tests/backend/spec_01_spectra_overlay.py
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
import json, time
from app.agent import tools as T
from app.chemistry.jobs import spectrum_source as SS
from app.chemistry.jobs.base import JobSpec, get_job_manager, delete_job_dir
from app.chemistry.jobs.summarize import job_context_summary
from app.plots import store as plot_store

WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}

mgr = get_job_manager()
jobs = {}
for tag, functional in (("b3lyp", "b3lyp"), ("camb3lyp", "cam-b3lyp")):
    jobs[tag] = mgr.submit(JobSpec(
        task="single_point", subtype="ee", method="dft", engine="pyscf", molecule=WATER,
        params={"basis": "sto-3g", "functional": functional, "n_states": 3},
    ))
opt_id = mgr.submit(JobSpec(task="opt", subtype="min", method="hf", engine="pyscf",
                            molecule=WATER, params={"basis": "sto-3g"}))
deadline = time.time() + 300
while time.time() < deadline:
    if all((mgr.status(j) or {}).get("status") in ("completed", "failed", "cancelled")
           for j in [*jobs.values(), opt_id]):
        break
    time.sleep(1.0)

out = {"statuses": {k: (mgr.status(v) or {}).get("status") for k, v in jobs.items()},
       "opt_status": (mgr.status(opt_id) or {}).get("status")}

# --- the resolver --------------------------------------------------------
x, y, meta, err = SS.total_spectrum_for_job(jobs["b3lyp"])
out["resolved"] = {"error": err, "n": int(len(x)) if x is not None else 0,
                   "peak": float(max(y)) if y is not None else None, "meta": meta}
out["kinds"] = {"ee": SS.spectrum_kind_for_job(jobs["b3lyp"]),
                "opt": SS.spectrum_kind_for_job(opt_id)}
out["no_spectrum"] = SS.total_spectrum_for_job(opt_id)[3]

# A wider broadening is a different curve, not the same one relabelled.
x2, y2, meta2, _ = SS.total_spectrum_for_job(jobs["b3lyp"], fwhm=1.2)
out["fwhm_respected"] = {"default": meta["fwhm"], "asked": meta2["fwhm"],
                         "curve_differs": bool(abs(float(max(y2)) - 1.0) < 1e-9
                                               and list(y[:50]) != list(y2[:50]))}

# Intensities are what give peaks their height; without them there is no
# spectrum to draw, and saying so beats drawing a flat line.
real_result = mgr.result
def _no_intensities(job_id):
    r = dict(real_result(job_id) or {})
    if job_id == jobs["b3lyp"]:
        s = dict(r.get("summary") or {})
        s["oscillator_strengths"] = [None, None, None]
        r["summary"] = s
    return r
SS.get_job_manager = lambda: type("M", (), {"result": staticmethod(_no_intensities)})()
out["no_intensities"] = SS.total_spectrum_for_job(jobs["b3lyp"])[3]
SS.get_job_manager = lambda: mgr

# --- the tagged context --------------------------------------------------
context = job_context_summary(jobs["b3lyp"])
out["context_has_spectrum"] = "Total spectrum" in context
out["context_says_normalized"] = "normalized to a peak of 1" in context
out["context_points_at_plot"] = 'plot(kind="spectra")' in context
out["opt_context_has_spectrum"] = "Total spectrum" in job_context_summary(opt_id)
# The spectrum is DESCRIBED, not tabulated. This used to parse a 64-row
# sampled table out of the context and assert its peak was exactly 1 -- while
# the very next line of that context told the reader not to rebuild the curve
# from those points. The table was being paid for on every status check and
# every attach for something nothing was supposed to use, so it is a band
# range and a peak position now.
out["context_has_table"] = "| eV | intensity |" in context
_m = __import__("re").search(r"available over ([-\d.eE]+) to ([-\d.eE]+) eV, peak at ([-\d.eE]+) eV", context)
out["context_band"] = [float(_m.group(1)), float(_m.group(2))] if _m else None
out["context_peak_eV"] = float(_m.group(3)) if _m else None

# --- the overlay ---------------------------------------------------------
state = {"owner_user_id": None, "active_job_ids": list(jobs.values())}
reply = T._plot_spectra({"job_ids": list(jobs.values()), "title": "two functionals"}, state)
out["overlay_reply"] = reply
plot_ids = []
if "plot id is " in reply:
    pid = reply.split("plot id is ")[-1].split(",")[0].strip()
    plot_ids.append(pid)
    rec = plot_store.get_plot(None, pid)
    data = (rec or {}).get("data") or {}
    out["overlay"] = {
        "n_series": len(data.get("series") or {}),
        "peaks": {k: max(v) for k, v in (data.get("series") or {}).items()},
        "shared_columns": all(len(v) == len(data.get("columns") or [])
                              for v in (data.get("series") or {}).values()),
        "kind": (rec or {}).get("kind"),
    }

nm_reply = T._plot_spectra({"job_ids": list(jobs.values()), "x_units": "nm"}, state)
if "plot id is " in nm_reply:
    pid = nm_reply.split("plot id is ")[-1].split(",")[0].strip()
    plot_ids.append(pid)
    cols = [float(c) for c in (plot_store.get_plot(None, pid) or {})["data"]["columns"]]
    out["nm_axis"] = {"ascending": cols == sorted(cols), "lo": cols[0], "hi": cols[-1]}

# One job with no spectrum among several is left out, not fatal.
mixed_in = T._plot_spectra({"job_ids": [jobs["b3lyp"], opt_id]}, state)
out["skips_unusable"] = {"drew": "plot id is " in mixed_in, "named": "produces no spectrum" in mixed_in}
if "plot id is " in mixed_in:
    plot_ids.append(mixed_in.split("plot id is ")[-1].split(",")[0].strip())

# An overlay has a real spec, so "show it in nm" is an edit rather than a
# new plot -- unlike a single-job spectrum, whose only parameter is width.
if plot_ids:
    edited = T._plot_edit(plot_ids[0], {"x_units": "nm"}, state)
    out["edit"] = {"reply": edited[:200], "same_id": plot_ids[0] in edited}
    rec = plot_store.get_plot(None, plot_ids[0])
    out["edit"]["versions"] = len((rec or {}).get("versions") or [])
    out["edit"]["axis_now_nm"] = float(((rec or {}).get("data") or {}).get("columns", ["0"])[0]) < 1000

# An IR spectrum cannot share an axis with a UV/Vis one.
real_total = SS.total_spectrum_for_job
def _as_ir(job_id, fwhm=None):
    x, y, meta, err = real_total(job_id, fwhm)
    if job_id == jobs["camb3lyp"] and meta:
        meta = dict(meta, kind="ir", axis_units="cm-1", label="IR absorption")
    return x, y, meta, err
T.spectrum_source.total_spectrum_for_job = _as_ir
out["mixed_axes"] = T._plot_spectra({"job_ids": list(jobs.values())}, state)
T.spectrum_source.total_spectrum_for_job = real_total

for pid in plot_ids:
    plot_store.delete_plot(None, pid)
for jid in [*jobs.values(), opt_id]:
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
        ["docker", "compose", "exec", "-T", "api", "python", "-c", IN_CONTAINER],
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

    print("== the seeded jobs ==")
    check("both excited-state jobs completed",
          set(r["statuses"].values()) == {"completed"}, json.dumps(r["statuses"]))

    print("\n== one resolver, one normalization ==")
    res = r["resolved"]
    check("an excited-state job resolves to a UV/Vis curve",
          res["error"] is None and res["meta"]["kind"] == "uvvis"
          and res["meta"]["axis_units"] == "eV", json.dumps(res)[:200])
    check("the curve peaks at exactly 1", res["peak"] is not None and abs(res["peak"] - 1.0) < 1e-12,
          str(res["peak"]))
    check("it is broadened the way the single-job plot broadens it",
          res["meta"]["fwhm"] == 0.2, str(res["meta"]["fwhm"]))
    check("the kind comes from the task, not from which fields happen to exist",
          r["kinds"] == {"ee": "uvvis", "opt": None}, json.dumps(r["kinds"]))
    check("a job with no spectrum says so rather than returning an empty curve",
          "produces no spectrum" in (r["no_spectrum"] or ""), str(r["no_spectrum"])[:120])
    check("a wider broadening really is a different curve, still peaking at 1",
          r["fwhm_respected"]["asked"] == 1.2 and r["fwhm_respected"]["curve_differs"],
          json.dumps(r["fwhm_respected"]))
    check("energies with no intensities are refused, not drawn flat",
          "no oscillator strengths" in (r["no_intensities"] or ""), str(r["no_intensities"])[:140])

    print("\n== the tagged job carries it ==")
    check("a tagged excited-state job carries its total spectrum", r["context_has_spectrum"])
    check("described, not tabulated -- no sampled curve in the context",
          r.get("context_has_table") is False,
          "a 64-row table was being paid for on every attach and every status check")
    check("it names the band it covers",
          isinstance(r.get("context_band"), list) and r["context_band"][0] < r["context_band"][1],
          str(r.get("context_band")))
    check("and where that band peaks, which is what a reply quotes off it",
          r.get("context_peak_eV") is not None
          and r["context_band"][0] <= r["context_peak_eV"] <= r["context_band"][1],
          str(r.get("context_peak_eV")))
    check("it says the curve is normalized", r["context_says_normalized"])
    check("and points at the plot rather than at rebuilding the curve",
          r["context_points_at_plot"])
    check("a job with no spectrum grows no spectrum section",
          r["opt_context_has_spectrum"] is False)

    print("\n== several methods, one axis ==")
    ov = r.get("overlay") or {}
    check("both spectra are drawn as one plot",
          ov.get("n_series") == 2 and ov.get("kind") == "spectra", json.dumps(ov)[:200])
    check("every curve reaches 1.0 in the cached table, not just on the figure",
          bool(ov.get("peaks")) and all(abs(v - 1.0) < 1e-9 for v in ov["peaks"].values()),
          json.dumps(ov.get("peaks")))
    check("every series shares one column set, i.e. one resampled grid",
          ov.get("shared_columns") is True)
    check("asking for nm gives an ascending wavelength axis",
          (r.get("nm_axis") or {}).get("ascending") is True, json.dumps(r.get("nm_axis")))
    check("a job with no spectrum is left out and named, not fatal",
          r["skips_unusable"]["drew"] and r["skips_unusable"]["named"],
          json.dumps(r["skips_unusable"]))
    ed = r.get("edit") or {}
    check("an overlay can be edited in place rather than re-plotted",
          ed.get("same_id") is True and ed.get("versions", 0) >= 2,
          json.dumps(ed)[:220])

    check("an IR and a UV/Vis spectrum are refused as a pair",
          "not on the same axis" in (r["mixed_axes"] or ""), str(r["mixed_axes"])[:160])

    print(f"\n{PASS}/{PASS + FAIL} checks passed in this script.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
