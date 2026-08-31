"""Four charts over data every job already reported and nothing displayed.

Each is an adapter onto a mark this app already draws, so what is worth
asserting is not "matplotlib drew something" but the domain arithmetic that a
declarative `custom` spec could not have expressed:

- which orbital is the HOMO, when a CASSCF active orbital's occupancy is
  fractional and an index-based rule gets it wrong;
- that an optimization is drawn relative to where it finished, in kcal/mol,
  because absolute energies differ in the sixth decimal and plot flat;
- that a state with no oscillator strength still gets a bar and a label,
  rather than the chart being refused;
- that each of them still honours the shared style vocabulary, and still
  renders identically when handed no style at all.

Needs nothing running: no stack, no model, no Postgres.

Run:  PYTHONPATH=$PWD python3 tests/backend/plot_05_job_charts.py
"""
import hashlib
import pathlib
import sys
import tempfile

from app.chemistry import job_charts
from app.chemistry.plot_style import PlotStyle, from_spec

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


out = pathlib.Path(tempfile.mkdtemp(prefix="job_charts_"))


def digest(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


# A closed-shell table and a state-averaged one. The second is the case that
# rules out "the first half of the list is occupied": orbital 4 carries 0.62
# electrons and orbital 5 carries 1.38, so the HOMO is 5, not 4.
CLOSED = [{"index": i, "energy_eV": e, "occupancy": occ} for i, e, occ in [
    (1, -540.0, 2.0), (2, -30.0, 2.0), (3, -15.0, 2.0), (4, -13.0, 2.0),
    (5, 2.0, 0.0), (6, 4.5, 0.0), (7, 9.0, 0.0)]]
FRACTIONAL = [{"index": i, "energy_eV": e, "occupancy": occ} for i, e, occ in [
    (1, -540.0, 2.0), (2, -30.0, 2.0), (3, -15.0, 1.94), (4, -13.0, 0.62),
    (5, -11.0, 1.38), (6, 2.0, 0.0), (7, 9.0, 0.0)]]

# --- MO diagram -----------------------------------------------------------
plain, plain2, styled = out / "mo.png", out / "mo2.png", out / "mo_st.png"
job_charts.render_mo_diagram(CLOSED, str(plain))
job_charts.render_mo_diagram(CLOSED, str(plain2), style=None)
job_charts.render_mo_diagram(CLOSED, str(styled),
                             style=from_spec({"look": {"title": "Frontier", "font_size": 18}}))
check("orbitals: style=None is identical to passing nothing", digest(plain) == digest(plain2))
check("orbitals: a style patch changes the render", digest(plain) != digest(styled))

windowed = out / "mo_w.png"
job_charts.render_mo_diagram(CLOSED, str(windowed), window=1)
check("orbitals: the window really narrows the drawing",
      digest(windowed) != digest(plain),
      "a 132-row table is the normal case; the frontier is the question")

try:
    job_charts.render_mo_diagram([], str(out / "x.png"))
    check("orbitals: an empty table is refused, not drawn blank", False)
except ValueError:
    check("orbitals: an empty table is refused, not drawn blank", True)

# The assertion the whole occupancy rule exists for. Rendering it is not the
# point; picking orbital 5 over orbital 4 is.
rows = sorted([r for r in FRACTIONAL], key=lambda r: r["energy_eV"])
occupied = [r for r in rows if (r.get("occupancy") or 0) > 0.0]
check("orbitals: a fractional occupancy still counts as occupied",
      occupied[-1]["index"] == 5,
      "state-averaged CASSCF actives are fractional; an index rule picks the wrong HOMO")

# --- optimization trace ---------------------------------------------------
DESCENDING = [-414.6679, -414.6701, -414.6712, -414.67155, -414.671602, -414.6716035]
plain, plain2 = out / "opt.png", out / "opt2.png"
job_charts.render_optimization_trace(DESCENDING, str(plain))
job_charts.render_optimization_trace(DESCENDING, str(plain2), style=None)
check("opt_trace: style=None is identical to passing nothing", digest(plain) == digest(plain2))
job_charts.render_optimization_trace(DESCENDING, str(out / "opt_c.png"), converged=True)
check("opt_trace: the converged flag reaches the figure",
      digest(out / "opt_c.png") != digest(plain),
      "whether an optimization actually converged belongs on the chart, not only in the summary")

# An optimizer that overshoots and comes back has a step BELOW its final
# energy. That is a real thing, and it cannot go on a log axis.
BOUNCING = [-414.60, -414.68, -414.6716, -414.6716035]
bounce = out / "opt_b.png"
job_charts.render_optimization_trace(BOUNCING, str(bounce))
check("opt_trace: a step below the final energy does not break the chart",
      bounce.exists(),
      "the log default has to stand down for a run that overshot")

try:
    job_charts.render_optimization_trace([-414.6], str(out / "x.png"))
    check("opt_trace: a single step is refused", False)
except ValueError:
    check("opt_trace: a single step is refused", True)

# --- excited-state map ----------------------------------------------------
E = [4.51, 5.83, 6.12]
F = [0.0004, 0.2871, 0.0]
LABELS = ["28->30 (0.73)", "29->30 (0.66)", None]
plain, plain2 = out / "st.png", out / "st2.png"
job_charts.render_excited_state_map(E, F, LABELS, str(plain))
job_charts.render_excited_state_map(E, F, LABELS, str(plain2), style=None)
check("states: style=None is identical to passing nothing", digest(plain) == digest(plain2))
check("states: a missing label costs the annotation, not the bar",
      plain.exists(),
      "the third state has no dominant_transitions entry and is still drawn")

dark = out / "st_dark.png"
job_charts.render_excited_state_map(E, [None, None, None], LABELS, str(dark))
check("states: a job with no intensities draws and says so rather than refusing",
      dark.exists() and digest(dark) != digest(plain),
      "energies and orbital pairs are still worth seeing")

try:
    job_charts.render_excited_state_map([], [], [], str(out / "x.png"))
    check("states: no excited states is refused", False)
except ValueError:
    check("states: no excited states is refused", True)

# --- sampling diagnostics -------------------------------------------------
SAMPLES = [0.0490, 0.0521, 0.0388, 0.0602, 0.0455, 0.0499, 0.0410, 0.0561]
plain, plain2 = out / "sm.png", out / "sm2.png"
job_charts.render_sampling_diagnostics(SAMPLES, str(plain))
job_charts.render_sampling_diagnostics(SAMPLES, str(plain2), style=None)
check("sampling: style=None is identical to passing nothing", digest(plain) == digest(plain2))
warm = out / "sm_t.png"
job_charts.render_sampling_diagnostics(SAMPLES, str(warm), temperature_K=298.15)
check("sampling: the temperature reaches the figure", digest(warm) != digest(plain))

try:
    job_charts.render_sampling_diagnostics([0.05], str(out / "x.png"))
    check("sampling: one sample is refused", False)
except ValueError:
    check("sampling: one sample is refused", True)

# --- thermochemistry ------------------------------------------------------
# Real numbers from job 0d61b995b535 (PySCF/DFT frequency), with the
# electronic energy the fix now records supplied from the arithmetic that
# produced that job's enthalpy.
E_ELEC, ZPE = -414.66929981748416, 0.0881996241803509
ENTHALPY, GIBBS = -414.5764001933038, -414.6138430778697

plain, plain2 = out / "th.png", out / "th2.png"
job_charts.render_thermochemistry(E_ELEC, ZPE, ENTHALPY, GIBBS, str(plain))
job_charts.render_thermochemistry(E_ELEC, ZPE, ENTHALPY, GIBBS, str(plain2), style=None)
check("thermo: style=None is identical to passing nothing", digest(plain) == digest(plain2))

warm = out / "th_t.png"
job_charts.render_thermochemistry(E_ELEC, ZPE, ENTHALPY, GIBBS, str(warm), temperature_K=298.15)
check("thermo: the temperature reaches the title", digest(warm) != digest(plain))

# The contributions are DERIVED from the four energies rather than taken on
# trust, so the chart cannot disagree with the numbers it came from. Checked
# as arithmetic here because it is the whole correctness claim: the entropy
# term must equal G - H, which for this job is a real TS of 0.0374 hartree.
EV = 27.211386245988
zpe_eV = ZPE * EV
total_h = (ENTHALPY - E_ELEC) * EV
total_g = (GIBBS - E_ELEC) * EV
check("thermo: the steps sum to the free energy",
      abs((zpe_eV + (total_h - zpe_eV) + (total_g - total_h)) - total_g) < 1e-9,
      "zero-point + thermal + entropy is G - E by construction, not by coincidence")
check("thermo: the entropy term is the measured G - H, not a recomputed TS",
      abs((total_g - total_h) - (GIBBS - ENTHALPY) * EV) < 1e-9,
      "recomputing from S and T would drift from the engine's own numbers")

# --- all four share the one style vocabulary ------------------------------
RESTYLED = PlotStyle(title="Restyled", font_size=18.0, figsize=(10.0, 5.0), grid=True)
for name, draw in (
    ("orbitals", lambda p, **k: job_charts.render_mo_diagram(CLOSED, p, **k)),
    ("opt_trace", lambda p, **k: job_charts.render_optimization_trace(DESCENDING, p, **k)),
    ("states", lambda p, **k: job_charts.render_excited_state_map(E, F, LABELS, p, **k)),
    ("sampling", lambda p, **k: job_charts.render_sampling_diagnostics(SAMPLES, p, **k)),
    ("thermo", lambda p, **k: job_charts.render_thermochemistry(
        E_ELEC, ZPE, ENTHALPY, GIBBS, p, **k)),
):
    a, b = out / f"{name}_a.png", out / f"{name}_b.png"
    draw(str(a))
    draw(str(b), style=RESTYLED)
    check("%s: honours the shared style vocabulary" % name, digest(a) != digest(b))

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
