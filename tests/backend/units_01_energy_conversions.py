#!/usr/bin/env python3
"""Energy units: one conversion, shared by the agent's tool and the plots.

Four units, all of them energy. Three are a scale factor apart and nm is
not -- it is inversely proportional to the other three -- which is the
whole reason this is a module rather than a couple of constants at each
call site. Two properties matter beyond the arithmetic:

- a RELATIVE energy can be reported in hartree or eV and in nothing else.
  "0.4 eV above the ground state" is a sentence; "0.4 nm above the ground
  state" is not, because a difference between two energies has no
  wavelength. The plot path takes a reference energy, so it is the one
  that has to refuse.
- the plots and the tool must not have separate implementations. A number
  in a reply disagreeing with the number on an axis is invisible until
  someone compares two figures, so they share one module and this checks
  the shared path end to end rather than the table alone.

Runs inside the api container: the end-to-end plot check seeds a real
scan, and a job's artifact paths are container paths. Needs the
docker-compose stack with an api image carrying the code under test.

    python3 tests/backend/units_01_energy_conversions.py
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
from app.chemistry import units
from app.chemistry.jobs import interpolate
from app.chemistry.jobs.base import JobSpec, get_job_manager, sub_job_ids_of, delete_job_dir
from app.agent import tools as T
from app.plots import store as plot_store

out = {}

# --- the table itself ----------------------------------------------------
out["hartree_to_ev"] = units.convert(1.0, "hartree", "eV")
out["hartree_to_cm1"] = units.convert(1.0, "hartree", "cm-1")
out["nm_to_ev"] = units.convert(400.0, "nm", "eV")
out["ev_roundtrip_nm"] = units.convert(units.convert(400.0, "nm", "eV"), "eV", "nm")
out["cm1_roundtrip"] = units.convert(units.convert(1000.0, "cm-1", "hartree"), "hartree", "cm-1")
out["synonyms"] = [units.canonical_unit(u) for u in ("Hartree", "EH", "electronvolt", "1/cm", "nanometers")]
out["zero_has_no_wavelength"] = units.convert_values([0.0], "eV", "nm")[1]
out["field_units"] = [units.unit_of_field(f) for f in
                      ("energies_hartree", "excitation_energies_eV[0]", "frequencies_cm-1",
                       "relative_energies_kcal_mol", "state_energies_per_image")]

# --- relative energies ---------------------------------------------------
rel, err = units.convert_values([-76.4, -76.3, None], "hartree", "eV", reference_hartree=-76.4)
out["relative_ev"] = rel
out["relative_ev_error"] = err
out["relative_nm_refused"] = units.convert_values([-76.3], "hartree", "nm", reference_hartree=-76.4)[1]
out["relative_cm1_refused"] = units.convert_values([-76.3], "hartree", "cm-1", reference_hartree=-76.4)[1]

# --- the agent's tool ----------------------------------------------------
out["tool_absolute"] = T.convert_energy_units.invoke(
    {"values": [0.15], "from_units": "hartree", "to_units": "nm"})
out["tool_relative_nm"] = T.convert_energy_units.invoke(
    {"values": [-76.3], "from_units": "hartree", "to_units": "nm", "reference_hartree": -76.4})

# --- the plot path's own rules, without paying for a plot ----------------
def _units_rule(spec, series, labels, columns):
    return T._apply_plot_units(spec, series, labels, columns)

series = [{"y_field": "energies_hartree"}]
cols = [[-76.4, -76.3]]
conv, ylabel, err = _units_rule({"y_units": "eV"}, series, ["E"], cols)
out["plot_absolute"] = {"values": conv, "ylabel": ylabel, "error": err}
conv, ylabel, err = _units_rule({"y_reference_hartree": -76.4}, series, ["E"], cols)
out["plot_reference_defaults_to_ev"] = {"values": conv, "ylabel": ylabel, "error": err}
_, _, err = _units_rule({"y_units": "nm", "y_reference_hartree": -76.4}, series, ["E"], cols)
out["plot_reference_nm_refused"] = err
_, _, err = _units_rule({"y_units": "eV"}, [{"y_field": "state_energies_per_image"}], ["E"], cols)
out["plot_unknown_source_refused"] = err
conv, _, err = _units_rule(
    {"y_units": "eV", "y_units_from": "hartree"}, [{"y_field": "state_energies_per_image"}], ["E"], cols)
out["plot_explicit_source"] = {"values": conv, "error": err}
_, _, err = _units_rule({"y_units": "eV"}, [{"y_field": "relative_energies_kcal_mol"}], ["E"], cols)
out["plot_kcal_refused"] = err

# --- end to end: a real scan, drawn in eV above its own first point ------
WATER = {"name": "water", "symbols": ["O", "H", "H"],
         "coords": [[0.0, 0.0, 0.117], [0.0, 0.757, -0.467], [0.0, -0.757, -0.467]],
         "charge": 0, "multiplicity": 1}
STRETCHED = {**WATER, "coords": [[0.0, 0.0, 0.117], [0.0, 1.057, -0.617], [0.0, -0.757, -0.467]]}
images, _w = interpolate.build_path(WATER, STRETCHED, 3, "linear")
mgr = get_job_manager()
master_id = mgr.submit_scan(
    JobSpec(task="interp_pes", subtype="", method="hf", engine="pyscf", molecule=images[0],
            params={"basis": "sto-3g", "n_points": 3, "interpolation_method": "linear",
                    "_end_molecule": STRETCHED, "_scan_start_molecule": WATER}),
    images, [float(i + 1) for i in range(3)], "image number (linear)",
)
deadline = time.time() + 240
while time.time() < deadline:
    if (mgr.status(master_id) or {}).get("status") in ("completed", "failed", "cancelled"):
        break
    time.sleep(1.0)

raw = ((mgr.result(master_id) or {}).get("summary") or {}).get("energies_hartree")
out["scan_energies_hartree"] = raw
state = {"owner_user_id": None, "active_job_ids": [master_id]}
reply = T._plot_custom(
    {"job_ids": [master_id], "x_field": "coordinate_values",
     "series": [{"y_field": "energies_hartree", "label": "Energy"}],
     "y_units": "eV", "y_reference_hartree": raw[0] if raw else 0.0,
     "title": "units e2e"},
    state,
)
out["plot_reply"] = reply
plot_id = reply.split("plot id is ")[-1].split(",")[0].strip() if "plot id is " in reply else None
record = plot_store.get_plot(None, plot_id) if plot_id else None
out["plot_cached_series"] = (record or {}).get("data", {}).get("series")

# clean up: the plot, the master, its images
if plot_id:
    plot_store.delete_plot(None, plot_id)
for jid in [*sub_job_ids_of(master_id), master_id]:
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


def close(a, b, tol=1e-6):
    return a is not None and abs(a - b) < tol


def main() -> int:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", IN_CONTAINER],
        cwd=REPO, capture_output=True, text=True, timeout=600,
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

    print("== the four units convert, both ways ==")
    check("1 hartree is 27.211386 eV", close(r["hartree_to_ev"], 27.211386245988, 1e-9),
          str(r["hartree_to_ev"]))
    check("1 hartree is 219474.63 cm-1", close(r["hartree_to_cm1"], 219474.6313, 1e-3),
          str(r["hartree_to_cm1"]))
    check("400 nm is 3.09960 eV", close(r["nm_to_ev"], 3.09960496, 1e-6), str(r["nm_to_ev"]))
    check("nm survives a round trip through eV", close(r["ev_roundtrip_nm"], 400.0, 1e-9))
    check("cm-1 survives a round trip through hartree", close(r["cm1_roundtrip"], 1000.0, 1e-6))
    check("the units a model might type are recognised",
          r["synonyms"] == ["hartree", "hartree", "eV", "cm-1", "nm"], str(r["synonyms"]))
    check("an energy of zero is refused a wavelength, not given infinity",
          "no wavelength" in (r["zero_has_no_wavelength"] or ""), str(r["zero_has_no_wavelength"]))

    print("\n== a field's own name says what it is in ==")
    check("units are read off the field names this project uses",
          r["field_units"] == ["hartree", "eV", "cm-1", "kcal/mol", None], str(r["field_units"]))

    print("\n== a relative energy is hartree or eV, and nothing else ==")
    check("values are re-expressed as distance above the reference",
          r["relative_ev_error"] is None
          and close(r["relative_ev"][0], 0.0) and close(r["relative_ev"][1], 2.7211386, 1e-6)
          and r["relative_ev"][2] is None,
          str(r["relative_ev"]))
    check("nm is refused for a difference, with the reason",
          "no wavelength" in (r["relative_nm_refused"] or ""), str(r["relative_nm_refused"])[:120])
    check("so is cm-1", "wavenumber" in (r["relative_cm1_refused"] or ""),
          str(r["relative_cm1_refused"])[:120])

    print("\n== the agent's tool ==")
    check("it answers an absolute conversion as a table",
          "| hartree | nm |" in r["tool_absolute"] and "303.756" in r["tool_absolute"],
          r["tool_absolute"][:160])
    check("it refuses nm for a referenced energy rather than inventing one",
          "no wavelength" in r["tool_relative_nm"], r["tool_relative_nm"][:120])

    print("\n== the plot path applies the same rules ==")
    check("y_units converts the drawn values",
          r["plot_absolute"]["error"] is None
          and close(r["plot_absolute"]["values"][0][0], -2079.0, 1.0),
          json.dumps(r["plot_absolute"])[:160])
    check("a reference implies eV and says so on the axis",
          r["plot_reference_defaults_to_ev"]["error"] is None
          and close(r["plot_reference_defaults_to_ev"]["values"][0][1], 2.7211386, 1e-6)
          and "relative to -76.4 hartree (eV)" in r["plot_reference_defaults_to_ev"]["ylabel"],
          json.dumps(r["plot_reference_defaults_to_ev"])[:200])
    check("a reference plus nm is refused", "no wavelength" in (r["plot_reference_nm_refused"] or ""))
    check("a field whose name carries no unit is asked about, not guessed",
          "y_units_from" in (r["plot_unknown_source_refused"] or ""),
          str(r["plot_unknown_source_refused"])[:140])
    check("...and y_units_from answers it",
          r["plot_explicit_source"]["error"] is None
          and close(r["plot_explicit_source"]["values"][0][0], -2079.0, 1.0))
    check("kcal/mol is named as the problem rather than read as hartree",
          "kcal/mol" in (r["plot_kcal_refused"] or ""), str(r["plot_kcal_refused"])[:140])

    print("\n== end to end: a real scan drawn relative to its own first point ==")
    raw = r["scan_energies_hartree"]
    drawn = (r["plot_cached_series"] or {}).get("Energy")
    expected = [(e - raw[0]) * 27.211386245988 for e in raw] if raw else None
    check("the scan produced energies to plot", bool(raw), str(raw))
    check("the plot cached the CONVERTED values, not the raw hartrees",
          bool(drawn) and all(close(a, b, 1e-9) for a, b in zip(drawn, expected)),
          f"drawn={drawn} expected={expected}")
    check("the first point sits at zero, since it is the reference",
          bool(drawn) and close(drawn[0], 0.0))

    print(f"\n{PASS}/{PASS + FAIL} checks passed in this script.")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
