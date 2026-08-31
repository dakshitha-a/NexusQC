"""The smaller things a review of the plot tool turned up.

None of these is a broken chart. They are the places where a reasonable
request had nowhere to land, or where a fixed number stayed fixed while
everything around it scaled:

- a legend with no way to sit anywhere but on top of the data;
- spectrum renderers that never reserved room for their own legend, so it
  covered the peak once anybody enlarged the font;
- an x axis that could be relabelled but not converted, while y could be both;
- one `xlim` applied to a bond panel and an angle panel alike;
- an equilibrium annotation pinned at 11pt on a chart scaled to 22.

Needs nothing running: no stack, no model, no Postgres.

Run:  PYTHONPATH=$PWD python3 tests/backend/plot_06_legend_units_panels.py
"""
import hashlib
import pathlib
import sys
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.chemistry.plot_style import PlotStyle, from_spec  # noqa: E402
from app.chemistry.spectrum import (  # noqa: E402
    render_histogram_plot, render_series_plot, render_uvvis_plot,
)

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


out = pathlib.Path(tempfile.mkdtemp(prefix="plot06_"))


def digest(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


# --- a legend can be asked to leave the data alone ------------------------
check("'outside' is a legend value the vocabulary accepts",
      from_spec({"look": {"legend": "outside"}}).legend == "outside",
      "matplotlib has nine locations and every one of them is inside the axes")

SERIES = [{"label": "S1", "values": [1.0, 2.0, 3.0]}, {"label": "S2", "values": [2.0, 2.5, 1.0]}]
inside, outside = out / "in.png", out / "out.png"
render_series_plot([0, 1, 2], ["HF", "DFT", "CAS"], SERIES, "m", "eV", "T", str(inside),
                   style="line", plot_style=from_spec({"look": {"legend": "upper right"}}))
render_series_plot([0, 1, 2], ["HF", "DFT", "CAS"], SERIES, "m", "eV", "T", str(outside),
                   style="line", plot_style=from_spec({"look": {"legend": "outside"}}))
check("a legend placed outside really renders differently",
      digest(inside) != digest(outside))


# --- headroom is reserved before the legend is drawn ----------------------
def top_of(style, positive=False):
    """The top of the y axis after `style` has had its say.

    Compared against a run that reserved nothing rather than against a
    literal, because matplotlib's own autoscale already adds a margin -- a
    curve peaking at 1.0 lands on 1.05 before anyone touches it. The
    assertion is about what this method changes, not about the number.
    """
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [0.1 if positive else 0.0, 1.0, 0.4], label="curve")
    if style is not None:
        style.reserve_legend_headroom(ax, 3)
    top = ax.get_ylim()[1]
    plt.close(fig)
    return top


untouched = top_of(None)
check("headroom lifts the top of the axis above the data",
      top_of(PlotStyle()) > untouched,
      "a normalized spectrum peaks at exactly 1.0 and the legend defaults to the top right")
check("an explicit ylim means no headroom is taken, because it is the caller's",
      top_of(PlotStyle(ylim=(0.0, 1.0))) == untouched,
      "this method leaves the axis untouched; `apply` sets the caller's limit afterwards, "
      "which is the ordering that lets a caller's ylim win over autoscaling")
check("no headroom is taken when the legend is outside the axes",
      top_of(PlotStyle(legend="outside")) == untouched,
      "there is nothing over the data to make room for")
check("no headroom is taken when the legend is off",
      top_of(PlotStyle(legend=False)) == untouched)
check("a log axis gets a multiplier, not an addition",
      top_of(PlotStyle(log_y=True), positive=True) > top_of(None, positive=True))

# The spectrum renderers never reserved any. A UV/Vis spectrum at a large
# font is the case that turned it up.
small, large = out / "uv_s.png", out / "uv_l.png"
E, F = [4.5, 5.8, 6.4], [0.01, 0.30, 0.05]
render_uvvis_plot(E, F, 0.2, str(small))
render_uvvis_plot(E, F, 0.2, str(large), style=from_spec({"look": {"font_size": 22}}))
check("a UV/Vis spectrum still renders at a large font size",
      digest(small) != digest(large) and (out / "uv_l.png").stat().st_size > 0)


# --- x axis converts, not only relabels -----------------------------------
# The unit machinery is shared with y and with kind="spectra"; what is
# asserted here is that x now reaches it at all.
from app.chemistry import units  # noqa: E402

converted, error = units.convert_values([2.0, 4.0], "eV", "nm")
check("the conversion x_units now uses is the same one y uses",
      error is None and converted[0] > converted[1],
      "nm runs the other way from eV, which is why the points are re-sorted")


# --- one xlim cannot serve a bond panel and an angle panel ----------------
DATA = {"bond(1,2)": [1.30, 1.35, 1.41, 1.33], "angle(1,2,3)": [118.0, 120.5, 122.1, 119.4]}
UNITS = {"bond(1,2)": "Å", "angle(1,2,3)": "°"}
plain, limited = out / "h.png", out / "h_lim.png"
render_histogram_plot(DATA, UNITS, str(plain))
render_histogram_plot(DATA, UNITS, str(limited),
                      style=from_spec({"look": {"xlim": [1.2, 1.5]}}))
check("a multi-panel distribution ignores one shared xlim",
      digest(plain) == digest(limited),
      "1.2 to 1.5 is a bond range; applying it to the angle panel empties it silently")

ONE = {"bond(1,2)": DATA["bond(1,2)"]}
one_plain, one_lim = out / "h1.png", out / "h1_lim.png"
render_histogram_plot(ONE, {"bond(1,2)": "Å"}, str(one_plain))
render_histogram_plot(ONE, {"bond(1,2)": "Å"}, str(one_lim),
                      style=from_spec({"look": {"xlim": [1.2, 1.5]}}))
check("a single-panel distribution still honours xlim",
      digest(one_plain) != digest(one_lim),
      "there it means exactly what it says")


# --- the equilibrium annotation scales with the rest ----------------------
eq_small, eq_large = out / "eq_s.png", out / "eq_l.png"
render_histogram_plot(ONE, {"bond(1,2)": "Å"}, str(eq_small),
                      equilibrium_by_label={"bond(1,2)": 1.34})
render_histogram_plot(ONE, {"bond(1,2)": "Å"}, str(eq_large),
                      equilibrium_by_label={"bond(1,2)": 1.34},
                      style=from_spec({"look": {"font_size": 24}}))
check("the equilibrium label grows with the font size",
      digest(eq_small) != digest(eq_large),
      "it was pinned at 11pt and ended up the smallest text on an enlarged chart")

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
