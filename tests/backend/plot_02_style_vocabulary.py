"""Every plot kind is restyleable, and an unstyled one is unchanged.

Four of the eight kinds could not be restyled at all before this. It was not
a missing spec key: render_uvvis_plot, render_ir_spectrum_plot,
render_wigner_ensemble_spectrum and render_pes_plot took no title, label,
colour or size argument, so their titles were f-strings in the function body
and plot(kind="edit") refused them outright. "Rename the title of my UV/Vis
spectrum" was impossible.

Two things have to hold at once, and the second is the one that makes the
first safe to ship: a styled render must actually change, and an UNSTYLED
render must be exactly what it always was, because people have these images
saved and referenced.

Needs nothing running: no stack, no model, no Postgres.

Run:  PYTHONPATH=$PWD python3 tests/backend/plot_02_style_vocabulary.py
"""
import hashlib
import pathlib
import sys
import tempfile

from app.agent.tools import _merge_plot_spec  # noqa: E402
from app.chemistry import plot_style  # noqa: E402
from app.chemistry.plot_style import DEFAULT_PALETTE, PlotStyle, PlotStyleError  # noqa: E402
from app.chemistry.spectrum import (  # noqa: E402
    render_ir_spectrum_plot, render_line_plot, render_pes_plot, render_series_plot,
    render_uvvis_plot, render_wigner_ensemble_spectrum,
)

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


out = pathlib.Path(tempfile.mkdtemp())


def digest(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


E = [5.10176071402066, 5.847494493977446]
F = [0.000243949073974109, 0.20377337663919087]
FR = [1200.0, 1650.0, 3400.0, 3.0]
IR = [30.0, 120.0, 8.0, 0.0]
COORD = [1.0, 1.2, 1.4, 1.6]
STATES = {"S0": [-76.4, -76.3, -76.2, -76.25], "S1": [-76.1, -76.0, -75.95, -76.02]}
SERIES = [{"label": "S1", "values": [1.0, 2.0, 3.0]},
          {"label": "S2", "values": [2.0, 2.5, None]}]

KINDS = {
    "uvvis": lambda p, **k: render_uvvis_plot(E, F, 0.2, p, **k),
    "ir": lambda p, **k: render_ir_spectrum_plot(FR, IR, 20.0, p, **k),
    "ensemble": lambda p, **k: render_wigner_ensemble_spectrum(E * 6, F * 6, [1, 2] * 6, 0.25, p, **k),
    "pes_scan": lambda p, **k: render_pes_plot(COORD, STATES, "r(O-H)", p, **k),
    "line": lambda p, **k: render_line_plot(COORD, STATES, "x", "y", "T", p, **k),
}

RESTYLED = PlotStyle(title="Restyled", xlabel="X", ylabel="Y", font_size=18.0,
                     figsize=(10.0, 5.0), grid=True, line_width=3.0)

for name, draw in KINDS.items():
    plain, plain2, styled = out / f"{name}.png", out / f"{name}_again.png", out / f"{name}_st.png"
    draw(str(plain))
    draw(str(plain2), style=None)
    draw(str(styled), style=RESTYLED)
    check("%s: passing style=None is identical to passing nothing" % name,
          digest(plain) == digest(plain2))
    check("%s: a style patch changes the render" % name,
          digest(plain) != digest(styled),
          "this is the assertion that was impossible for four kinds")

# render_series_plot names the mark `style`, so its look parameter is
# `plot_style`. Both are real and they are not the same thing.
sp, sp_styled = out / "series.png", out / "series_st.png"
render_series_plot([0, 1, 2], ["HF", "DFT", "CASSCF"], SERIES, "m", "eV", "T", str(sp), style="levels")
render_series_plot([0, 1, 2], ["HF", "DFT", "CASSCF"], SERIES, "m", "eV", "T", str(sp_styled),
                   style="levels", plot_style=RESTYLED)
check("series: mark and look are separate parameters",
      digest(sp) != digest(sp_styled))

# --- the defaults must not have drifted ------------------------------------
d = PlotStyle()
check("unset line width defers to the renderer's own",
      d.lw(2.5) == 2.5 and d.lw(1.5) == 1.5,
      "a levels tick is 2.5pt and an ensemble total 2.0pt; one number for both would restyle them")
check("unset marker size defers to the renderer's own", d.ms(3.0) == 3.0)
check("unset palette leaves a single-accent renderer alone",
      d.accent("tab:blue") == "tab:blue")
check("unset palette leaves matplotlib's own colour cycle alone",
      d.cycle_color(0) is None,
      "render_line_plot never set colours; forcing one would change every saved scan plot")
check("a set palette wins for both", PlotStyle(palette=("#123456",)).accent("tab:blue") == "#123456"
      and PlotStyle(palette=("#123456",)).cycle_color(0) == "#123456")
check("the multi-series palette is unchanged", d.color(0) == DEFAULT_PALETTE[0])

# --- from_spec: the mark and the look cannot be confused -------------------
check("look is read from spec['look']",
      plot_style.from_spec({"look": {"title": "T"}}).title == "T")
check("a dict-valued spec['style'] is read as the look",
      plot_style.from_spec({"style": {"title": "T"}}).title == "T",
      "'style' is the word anyone reaches for first")
check("a string spec['style'] is the MARK and is left alone",
      plot_style.from_spec({"style": "levels"}).title is None,
      "reading it as a look would break every custom plot")

try:
    plot_style.from_spec({"look": {"nope": 1}})
    check("an unknown look key is refused", False)
except PlotStyleError as e:
    check("an unknown look key is refused, naming the valid ones",
          "nope" in str(e) and "font_size" in str(e),
          "silently ignoring it would re-render an identical image, which reads as being ignored")
try:
    plot_style.from_spec({"look": {"fmt": "tiff"}})
    check("an unsupported export format is refused", False)
except PlotStyleError:
    check("an unsupported export format is refused", True)
try:
    plot_style.from_spec({"look": {"xlim": 5}})
    check("a malformed pair is refused", False)
except PlotStyleError:
    check("a malformed pair is refused", True)

# --- editing merges the look rather than replacing it ----------------------
current = {"kind": "uvvis", "width": 0.2, "look": {"title": "First", "font_size": 16}}
merged = _merge_plot_spec(current, {"look": {"title": "Second"}})
check("an edit keeps look keys it did not mention",
      merged["look"] == {"title": "Second", "font_size": 16},
      "'make the title bigger' must not drop the axis labels set two turns ago")
check("an edit keeps the rest of the spec", merged["width"] == 0.2)
cleared = _merge_plot_spec(current, {"look": {"font_size": None}})
check("a null inside look removes just that key",
      cleared["look"] == {"title": "First"})
kept = _merge_plot_spec({"style": "levels"}, {"look": {"title": "T"}})
check("a mark and a look coexist in one spec",
      kept["style"] == "levels" and kept["look"] == {"title": "T"})

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
