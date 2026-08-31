"""A style key that is accepted has to reach the figure.

`plot_02_style_vocabulary.py` proves each renderer *can* be restyled. It
cannot catch the failure this file is about, and the reason is worth stating
because it is the trap: plot_02 restyles with seven keys at once
(`PlotStyle(title=..., xlabel=..., ylabel=..., font_size=18, figsize=...,
grid=True, line_width=3)`) and asserts the image changed. It changes. A single
key inside that bundle can be completely inert and every assertion still
passes, and one was.

Four defects, all of the same shape -- the tool accepts a request, reports the
plot as drawn, and the plot comes back identical:

1. `font_size` moved nothing a reader would call the font. The four specific
   sizes were absolute defaults (16/14/12/12) and each is an rcParam that
   overrides `font.size` for the text it governs, so a bigger base font left
   the title, the axis labels, the ticks and the legend at exactly their old
   size. "Make the fonts bigger" was the request that exposed it.
2. `plot(kind="comparison")` never passed `spec` on at all, so `look` was
   validated, accepted, and dropped on the floor.
3. `plot_wigner_ensemble_spectrum` read the JOB's spec into the same local the
   PLOT's spec arrived in, so an ensemble spectrum could not be restyled and
   the saved record stored the job's molecule and params as its chart spec.
4. A distribution (`kind="histogram"`) took no style at all and had no branch
   in `_plot_edit`, so it answered "which this app cannot redraw".

The first and last are checked against the real renderers. The two in the
middle are wiring, so they are checked by standing in for the function the
value has to arrive at and asserting on what it receives -- no stack, no
model, no Postgres, and no job on disk.

Run:  PYTHONPATH=$PWD python3 tests/backend/plot_03_style_actually_lands.py
"""
import hashlib
import pathlib
import sys
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.agent import tools  # noqa: E402
from app.chemistry.plot_style import PlotStyle, from_spec  # noqa: E402
from app.chemistry.spectrum import render_histogram_plot  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


out = pathlib.Path(tempfile.mkdtemp())


def digest(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


# --- 1. font_size is a real base -------------------------------------------
# The numbers an unstyled figure has always drawn with. Asserted literally
# rather than derived, because the whole point of deriving them from a base is
# that the derivation must not move them.
HISTORIC = {"font.size": 13.0, "axes.titlesize": 16.0, "axes.labelsize": 14.0,
            "xtick.labelsize": 12.0, "ytick.labelsize": 12.0, "legend.fontsize": 12.0}
check("an unstyled figure's text sizes are unchanged", PlotStyle().rc() == HISTORIC,
      "people have these images saved; the defaults are not free to drift")

bigger = from_spec({"look": {"font_size": 26}}).rc()
moved = [k for k, v in HISTORIC.items() if bigger[k] <= v]
check("font_size alone enlarges title, labels, ticks and legend", not moved,
      "still at their old size: %s" % ", ".join(moved) if moved else "all four scale with the base")

pinned = from_spec({"look": {"font_size": 26, "title_size": 9}}).rc()
check("a specific size named by the caller still wins over the base",
      pinned["axes.titlesize"] == 9.0 and pinned["axes.labelsize"] > 14.0)

# The measurement that matters: rc() is a dict of intentions, and matplotlib
# is what decides whether they reach the text.
sizes = {}
for name, look in (("default", {}), ("bigger", {"font_size": 26})):
    with plt.rc_context(from_spec({"look": look}).rc()):
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1], label="a")
        ax.set_title("T")
        ax.set_xlabel("X")
        ax.legend()
        sizes[name] = (ax.title.get_fontsize(), ax.xaxis.label.get_fontsize(),
                       ax.get_xticklabels()[0].get_fontsize(),
                       ax.get_legend().get_texts()[0].get_fontsize())
        plt.close(fig)
check("matplotlib really draws the larger text",
      all(b > d for b, d in zip(sizes["bigger"], sizes["default"])),
      "default %s -> font_size=26 %s" % (sizes["default"], sizes["bigger"]))

# --- 2. a distribution is stylable and unstyled is unchanged ----------------
DATA = {"bond(7,8)": [1.0, 1.05, 1.1, 1.02, 1.08, 1.12], "angle(1,2,3)": [104.0, 106.5, 103.2, 105.1]}
UNITS = {"bond(7,8)": "Å", "angle(1,2,3)": "°"}
EQ = {"bond(7,8)": 1.06}

plain, plain2, styled = out / "h.png", out / "h2.png", out / "h_st.png"
render_histogram_plot(DATA, UNITS, str(plain), equilibrium_by_label=EQ)
render_histogram_plot(DATA, UNITS, str(plain2), equilibrium_by_label=EQ, style=None)
render_histogram_plot(DATA, UNITS, str(styled), equilibrium_by_label=EQ,
                      style=from_spec({"look": {"title": "Uracil Wigner spread", "font_size": 20,
                                                "grid": True}}))
check("histogram: passing style=None is identical to passing nothing",
      digest(plain) == digest(plain2))
check("histogram: a style patch changes the render", digest(plain) != digest(styled),
      "this was the last renderer taking no style at all")

# A title on a multi-panel figure is the figure's, never each panel's: the
# panels' own titles are the only thing distinguishing them.
with plt.rc_context({}):
    titled = out / "h_title.png"
    render_histogram_plot(DATA, UNITS, str(titled),
                          style=from_spec({"look": {"title": "One title"}}))
check("histogram: a title renders (as the figure's, over the panels)",
      digest(titled) != digest(plain))


# --- 3. comparison forwards the caller's look ------------------------------
# `_plot_custom` is where a comparison's look has to arrive. Standing in for
# it is the whole assertion: plot() used to call plot_job_comparison without
# `spec`, so nothing arrived and nothing could be observed downstream either.
seen = {}


def capture_custom(spec, state, plot_id=None):
    seen["spec"] = spec
    return "PLOT_ARTIFACT plot_id=stub version=v1\nstub"


def capture_result(job_id):
    return {"status": "completed", "summary": {"total_energy_hartree": -76.0 - len(job_id) * 1e-3}}


class _StubManager:
    result = staticmethod(capture_result)


real_custom, real_manager = tools._plot_custom, tools.get_job_manager
tools._plot_custom = capture_custom
tools.get_job_manager = lambda: _StubManager()
try:
    tools.plot.func(kind="comparison", job_ids=["aaaaaaaaaaaa", "bbbbbbbbbbbb"],
                    spec={"field": "energy", "look": {"title": "Method comparison", "font_size": 18}},
                    state={"active_job_ids": []})
finally:
    tools._plot_custom, tools.get_job_manager = real_custom, real_manager

look = (seen.get("spec") or {}).get("look")
check("comparison: the caller's look reaches the drawing pipeline",
      look == {"title": "Method comparison", "font_size": 18},
      "plot() used to drop `spec` entirely, so the restyle was accepted and discarded")
check("comparison: the front door still owns the mark and the series",
      (seen.get("spec") or {}).get("style") == "bar" and len(seen["spec"]["series"]) == 1,
      "a passthrough must not let the caller redefine what a comparison IS")


# --- 4. an ensemble spectrum keeps the caller's spec -----------------------
# The job's spec used to overwrite it before either the renderer or the record
# saw it. Stopping at _save_plot is enough: that is where both the style and
# the stored spec are decided.
captured = {}


def capture_save(state, kind, label, spec, job_ids, data, render, plot_id=None, origin="agent"):
    captured["spec"] = spec
    return None, None, "stopped here on purpose"


JOB_SPEC = {"task": "wigner_spectra", "engine": "pyscf", "molecule": {"symbols": ["O"]},
            "params": {"fwhm_eV": 0.3}, "parent_job_id": "cccccccccccc"}

saved = (tools._ensemble_master_or_error, tools.sub_job_ids_of, tools.pool_ensemble_transitions,
         tools.read_spec, tools.read_meta, tools._save_plot)
tools._ensemble_master_or_error = lambda job_id: ({"status": "completed"}, None)
tools.sub_job_ids_of = lambda job_id: ["s1", "s2"]
tools.pool_ensemble_transitions = lambda ids: (
    {"energies_eV": [5.1, 5.8], "oscillator_strengths": [0.01, 0.2], "state_indices": [1, 2]},
    {"n_no_intensity": 0, "n_failed_or_pending": 0, "n_sub_jobs": 2, "n_completed": 2},
)
tools.read_spec = lambda job_id: dict(JOB_SPEC)
tools.read_meta = lambda job_id: {}
tools._save_plot = capture_save
try:
    tools.plot_wigner_ensemble_spectrum(
        job_id="dddddddddddd", state={"active_job_ids": []},
        spec={"look": {"title": "Uracil ensemble", "font_size": 18}})
finally:
    (tools._ensemble_master_or_error, tools.sub_job_ids_of, tools.pool_ensemble_transitions,
     tools.read_spec, tools.read_meta, tools._save_plot) = saved

stored = captured.get("spec") or {}
check("ensemble: the caller's look survives to the record",
      stored.get("look") == {"title": "Uracil ensemble", "font_size": 18},
      "the job spec used to land in the same local and replace it")
check("ensemble: the job's own spec is not stored as the chart's",
      not ({"molecule", "params", "engine", "parent_job_id", "task"} & set(stored)),
      "a plot spec describes the chart, not the calculation behind it")
check("ensemble: the job's stored broadening is still the default",
      stored.get("width") == 0.3,
      "reading fwhm_eV out of the job spec was correct and must not have been lost with the clobber")


# --- 5. a distribution can be edited ---------------------------------------
edited = {}


def capture_histogram(job_id, task, parameters, state=None, plot_spec=None, plot_id=None):
    edited.update(job_id=job_id, task=task, parameters=parameters, plot_spec=plot_spec,
                  plot_id=plot_id)
    return "PLOT_ARTIFACT plot_id=%s version=v2\nstub" % plot_id


PARAMS = [{"type": "bond", "atoms": [7, 8]}]
saved_edit = (tools.plot_store.get_plot, tools.read_spec, tools._geometry_parameters_histogram)
tools.plot_store.get_plot = lambda owner, pid: {
    "plot_id": pid, "kind": "histogram", "job_ids": ["eeeeeeeeeeee"],
    "spec": {"kind": "histogram", "parameters": PARAMS},
}
tools.read_spec = lambda job_id: {"task": "wigner_spectra"}
tools._geometry_parameters_histogram = capture_histogram
try:
    reply = tools._plot_edit("pdeadbeef123", {"look": {"title": "Spread at 298 K"}},
                             {"active_job_ids": []})
finally:
    (tools.plot_store.get_plot, tools.read_spec,
     tools._geometry_parameters_histogram) = saved_edit

check("histogram: an edit is no longer refused",
      "cannot redraw" not in reply, reply.splitlines()[0] if reply else "")
check("histogram: the edit redraws the same plot id, with the patch merged",
      edited.get("plot_id") == "pdeadbeef123"
      and (edited.get("plot_spec") or {}).get("look") == {"title": "Spread at 298 K"}
      and edited.get("parameters") == PARAMS,
      "the parameters come from the record, the task from the source job's spec")

# --- 6. an export format nothing implements is refused, not ignored --------
# `fmt` was accepted and read by nobody: the store writes `<version>.png` and
# the routes serve and name a PNG, so "save it as an SVG" produced a PNG and
# said it had worked.
try:
    from_spec({"look": {"fmt": "svg"}})
    check("an unimplemented export format is refused rather than silently ignored", False)
except Exception as e:
    check("an unimplemented export format is refused rather than silently ignored",
          "not available yet" in str(e), str(e))
check("png is still accepted", from_spec({"look": {"fmt": "png"}}).fmt == "png")

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
