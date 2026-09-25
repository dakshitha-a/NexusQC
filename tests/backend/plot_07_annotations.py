"""Text on a plot: `value_labels` and `annotations`, and the refusal that
keeps either from being dropped silently.

Why this exists. On 2026-09-24 the user asked the agent to "annotate the plot
with the energies for each method". The agent sent a well-formed
`spec["annotations"]` list. The plot tool had no annotation support, and
nothing checked a spec's top-level keys, so the list was stored and not
drawn. The user said "I don't see the annotations", and the agent fell back
to writing the numbers into the x-axis labels.

What is checked, and how:

  A. The renderer, with no jobs involved. A five-column levels chart of the
     uracil S1/S2 energies from that conversation (values copied from its
     plot record) is drawn with and without value_labels, and every label's
     text is read back off the matplotlib axes. The pass condition is that
     the ten labels are exactly the ten values at two decimals, and that
     each levels label sits to the RIGHT of its tick at the tick's own
     height, so labels of two states 0.24 eV apart cannot collide.
  B. Annotations on a category axis (by column label, by the first line of a
     two-line label, and by slot number), on a numeric-axis spectrum
     renderer, and the three refusals: a column that is not on the axis,
     a text x on a numeric axis, and a malformed entry.
  C. Through the agent's `plot` tool on the real uracil jobs when they are
     present on disk (skipped otherwise): an unknown top-level key is
     refused naming the valid ones, a column named by job id resolves,
     the reply says the labels were drawn, the context summary the model
     reads lists them, and an edit with `annotations: null` removes them.
     Plots are saved under a scratch owner and deleted afterwards.

Run:  PYTHONPATH=$PWD python3 tests/backend/plot_07_annotations.py
"""
import pathlib
import shutil
import sys
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.chemistry import spectrum  # noqa: E402
from app.chemistry.plot_style import PlotStyle, PlotStyleError, from_spec  # noqa: E402

failures = []
out = pathlib.Path(tempfile.mkdtemp())


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


COLUMNS = ["CASSCF (BAGEL)", "CASSCF (PySCF)", "xms-CASPT2 (BAGEL)", "L-PDFT (PySCF)", "NEVPT2 (PySCF)"]
S1 = [5.133911561639092, 5.1325522891590225, 4.933179579026804, 5.275720785576976, 5.2946483092064645]
S2 = [6.743895542220576, 6.744535214455933, 5.166441797007991, 5.590004021450617, 6.160871757752899]
SERIES = [{"label": "S1", "values": S1}, {"label": "S2", "values": S2}]


def captured_axes(render):
    """Run a renderer and keep its axes, by standing in for savefig/close."""
    kept = {}
    real_close = plt.close

    def keep(fig=None):
        if fig is not None and hasattr(fig, "axes"):
            kept["ax"] = fig.axes[0]
    plt.close = keep
    try:
        render()
    finally:
        plt.close = real_close
    return kept.get("ax")


def texts(ax):
    return [c for c in ax.texts]


# --- A. value_labels on the renderer ----------------------------------------
ax = captured_axes(lambda: spectrum.render_series_plot(
    list(range(5)), COLUMNS, SERIES, "", "Excitation energy (eV)", "t", str(out / "a.png"),
    style="levels", plot_style=PlotStyle(), value_labels=".2f"))
labels = sorted(t.get_text() for t in texts(ax))
expected = sorted(format(v, ".2f") for v in S1 + S2)
check("levels: ten labels, exactly the drawn values at two decimals", labels == expected,
      "got %s" % labels)
right_of_tick = all(t.xy[0] == p + 0.30 and t.xy[1] == v and t.get_ha() == "left"
                    for t, (p, v) in zip(texts(ax), [(p, v) for s in SERIES
                                                     for p, v in enumerate(s["values"])]))
check("levels: each label sits at its tick's right end and height", right_of_tick)

ax = captured_axes(lambda: spectrum.render_series_plot(
    list(range(5)), COLUMNS, SERIES, "", "E", "t", str(out / "b.png"), style="levels",
    plot_style=PlotStyle()))
check("without value_labels nothing is written", len(texts(ax)) == 0)

ax = captured_axes(lambda: spectrum.render_series_plot(
    list(range(5)), COLUMNS, [{"label": "S1", "values": [5.13, None, 4.93, None, 5.29]}], "", "E", "t",
    str(out / "c.png"), style="bar", plot_style=PlotStyle(), value_labels=".3f"))
check("bar: a gap gets no label, the rest use the requested format",
      sorted(t.get_text() for t in texts(ax)) == ["4.930", "5.130", "5.290"])

# --- B. annotations ----------------------------------------------------------
def render_with(notes, style="levels", columns=COLUMNS):
    st = from_spec({"annotations": notes})
    return captured_axes(lambda: spectrum.render_series_plot(
        list(range(len(columns))), columns, SERIES, "", "E", "t", str(out / "d.png"),
        style=style, plot_style=st))


ax = render_with([{"text": "near-degenerate", "x": "xms-CASPT2 (BAGEL)", "y": 5.17, "arrow": True}])
note = [t for t in texts(ax) if t.get_text() == "near-degenerate"]
check("a column named by its label resolves to its slot", note and note[0].xy == (2.0, 5.17))
check("arrow: true draws an arrow", note and note[0].arrow_patch is not None)

two_line = [c + "\nS1 / S2" for c in COLUMNS]
ax = render_with([{"text": "x", "x": "NEVPT2 (PySCF)", "y": 6.0}], columns=two_line)
check("the first line of a two-line label finds the column",
      [t.xy for t in texts(ax) if t.get_text() == "x"] == [(4.0, 6.0)])

ax = render_with([{"text": "slot", "x": 1, "y": 6.0}])
check("a number on a category axis is the slot index",
      [t.xy for t in texts(ax) if t.get_text() == "slot"] == [(1.0, 6.0)])

try:
    render_with([{"text": "x", "x": "CASPT2", "y": 5.0}])
    check("a column that is not on the axis is refused", False, "rendered")
except PlotStyleError as e:
    check("a column that is not on the axis is refused, naming the real ones",
          "not a column" in str(e) and "NEVPT2 (PySCF)" in str(e), str(e)[:120])

uv = str(out / "uv.png")
st = from_spec({"annotations": [{"text": "bright", "x": 5.3, "y": 0.2, "arrow": True}]})
ax = captured_axes(lambda: spectrum.render_uvvis_plot([5.1, 5.3, 6.2], [0.01, 0.2, 0.05], 0.2, uv, style=st))
check("a numeric-axis kind (UV/Vis) draws a numeric annotation",
      [t.get_text() for t in texts(ax)].count("bright") == 1)
try:
    st = from_spec({"annotations": [{"text": "x", "x": "S1", "y": 0.2}]})
    captured_axes(lambda: spectrum.render_uvvis_plot([5.1, 5.3], [0.01, 0.2], 0.2, uv, style=st))
    check("a text x on a numeric axis is refused", False, "rendered")
except PlotStyleError as e:
    check("a text x on a numeric axis is refused", "numeric" in str(e), str(e)[:100])

for bad, why in (([{"x": 0, "y": 1}], "needs 'text'"), ([{"text": "a", "x": 0}], "needs 'y'"),
                 ([{"text": "a", "x": 0, "y": 1, "font": 3}], "unknown key"), ("oops", "must be a list")):
    try:
        from_spec({"annotations": bad})
        check("malformed annotation refused (%s)" % why, False, "accepted")
    except PlotStyleError as e:
        check("malformed annotation refused (%s)" % why, why in str(e), str(e)[:90])

check("annotations written inside look are read, not refused",
      len(from_spec({"look": {"annotations": [{"text": "a", "x": 0, "y": 1}]}}).annotations) == 1)

# --- C. through the agent's plot tool ----------------------------------------
from app.agent import tools  # noqa: E402
from app.plots import store as plot_store  # noqa: E402
from app.chemistry.jobs.base import get_job_manager  # noqa: E402

JOBS = ["a98746cbcd2b", "dfbfd378a62d", "2d8ef7271d7a", "5b9a8a60ab63", "0444015f7651"]
OWNER = "qatest_plot07"
state = {"owner_user_id": OWNER, "active_job_ids": JOBS}
plot_fn = tools.plot.func

refused = plot_fn(kind="custom", spec={"annotation": []}, state=state)
check("an unknown top-level key is refused, naming the valid ones",
      "Unknown plot spec key(s): annotation" in refused and "annotations" in refused, refused[:100])

available = all((get_job_manager().result(j) or {}).get("status") == "completed" for j in JOBS)
if not available:
    print("[SKIP] the uracil jobs are not on disk here, so the end-to-end part is skipped")
else:
    try:
        spec = {"job_ids": JOBS, "style": "levels", "value_labels": True,
                "series": [{"y_field": "excitation_energies_eV[0]", "label": "S1"},
                           {"y_field": "excitation_energies_eV[1]", "label": "S2"}],
                "x_labels": dict(zip(JOBS, COLUMNS)),
                "annotations": [{"text": "near-degenerate", "x": "2d8ef7271d7a", "y": 5.17, "arrow": True}]}
        reply = plot_fn(kind="custom", spec=spec, state=state)
        check("the tool draws it and says the labels are there",
              reply.startswith("PLOT_ARTIFACT") and "written on its mark" in reply
              and "1 annotation(s) drawn" in reply, reply.split("\n")[1][:160] if "\n" in reply else reply)
        plot_id = reply.split("plot_id=")[1].split()[0]
        summary = plot_store.context_summary(OWNER, plot_id)
        check("the model's view of the plot lists the labels and the note",
              "written on its mark" in summary and "near-degenerate" in summary)
        reply = plot_fn(kind="edit", plot_id=plot_id, spec={"annotations": None}, state=state)
        record = plot_store.get_plot(OWNER, plot_id)
        check("an edit with annotations: null removes them",
              reply.startswith("PLOT_ARTIFACT") and "annotations" not in record["spec"]
              and "annotation(s) drawn" not in reply)
        png = plot_store.version_path(OWNER, plot_id, plot_store.latest_version(record))
        shutil.copy(png, out / "uracil_edit.png")
        print("[INFO] images for a human look: %s" % out)
    finally:
        for record in plot_store.list_plots(OWNER):
            plot_store.delete_plot(OWNER, record["plot_id"])
        owner_dir = plot_store.PLOTS_DIR / OWNER
        if owner_dir.exists() and not any(owner_dir.iterdir()):
            owner_dir.rmdir()

print()
print("%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
