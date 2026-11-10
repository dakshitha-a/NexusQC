"""Per-curve line styles, markers on dense lines, long titles and legends.

Found on 2026-11-09 while making the furan ensemble figure for the thesis:

- asked to dash one curve of a spectra overlay, the agent said "now dashed"
  and saved a new version, but the renderer had one line style for every
  curve and the stored spec's per-series key was ignored;
- the overlay put a circle on each of its 2000 grid points;
- a 68-character title ran off an 8 in figure;
- the legend sat on both normalised peak tops.

In-process, no stack and no model needed:

    PYTHONPATH=$PWD python3 tests/backend/plot_08_series_styles_and_layout.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

from app.agent.tools import PLOT_SPEC_KEYS, _plot_patch_problem
from app.chemistry.plot_style import (PlotStyle, PlotStyleError, default_marker,
                                      from_spec, parse_line_style)
from app.chemistry.spectrum import render_line_plot

PASS = FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS += ok
    FAIL += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok or not detail else f"\n         {detail}"))


def main() -> int:
    print("== line style names ==")
    check("dashed -> --", parse_line_style("dashed") == "--")
    check("dotted -> :", parse_line_style("Dotted") == ":")
    try:
        parse_line_style("wavy")
        check("an unknown style is refused", False)
    except PlotStyleError as e:
        check("an unknown style is refused, naming the ones that work", "dashed" in str(e), str(e))

    print("\n== what the renderer cannot draw is refused, not stored ==")
    check("line_styles is a spec key", "line_styles" in PLOT_SPEC_KEYS)
    check("a spectra edit with series is refused",
          "line_styles" in (_plot_patch_problem("spectra", {"series": [{"label": "X", "dash": "--"}]}) or ""))
    check("line_styles on a single-curve kind is refused",
          _plot_patch_problem("uvvis", {"line_styles": {"a": "dashed"}}) is not None)
    check("a custom series key nothing reads is refused by name",
          "dash" in (_plot_patch_problem("custom", {"series": [{"y_field": "e", "dash": "--"}]}) or ""))
    check("a custom series line_style is accepted",
          _plot_patch_problem("custom", {"series": [{"y_field": "e", "line_style": "dotted"}]}) is None)
    check("spectra line_styles are accepted",
          _plot_patch_problem("spectra", {"line_styles": {"abc": "dashed"}}) is None)

    print("\n== markers only on sparse lines ==")
    st = PlotStyle()
    check("2000 points: no marker", default_marker(st, 2000) is None)
    check("12 points: circles", default_marker(st, 12) == "o")
    check("an asked-for marker is kept on a dense line", default_marker(PlotStyle(marker="s"), 2000) == "s")

    print("\n== long titles wrap ==")
    title = "Furan UV/Vis: nuclear ensemble vs single geometry (B3LYP/def2-SVP)"
    wrapped = PlotStyle(title=title, figsize=(8, 6))._wrapped_title()
    check("the thesis title wraps on an 8 in figure", "\n" in wrapped, wrapped)
    check("a short title is left alone", PlotStyle(title="Spectra")._wrapped_title() == "Spectra")
    check("a title broken by hand is left as written",
          PlotStyle(title="A\nB" + "x" * 90)._wrapped_title() == "A\nB" + "x" * 90)

    print("\n== the overlay draws, dashes one curve, and keeps the legend off the peaks ==")
    import matplotlib.pyplot as plt
    drawn = {}
    real_savefig = plt.Figure.savefig

    def spy(fig, *a, **kw):
        ax = fig.axes[0]
        drawn["styles"] = {ln.get_label(): ln.get_linestyle() for ln in ax.get_lines()}
        drawn["markers"] = {ln.get_label(): ln.get_marker() for ln in ax.get_lines()}
        drawn["ytop"] = ax.get_ylim()[1]
        return real_savefig(fig, *a, **kw)

    plt.Figure.savefig = spy
    try:
        x = np.linspace(4, 9, 2000)
        y = np.exp(-0.5 * ((x - 6) / 0.2) ** 2)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o.png"
            render_line_plot(list(x), {"Ensemble": list(y), "Single": list(y)}, "E", "I", title,
                             str(out), series_styles={"Single": "--"})
            check("a file was written", out.exists() and out.stat().st_size > 0)
    finally:
        plt.Figure.savefig = real_savefig
    check("the named curve is dashed and the other solid",
          drawn.get("styles") == {"Ensemble": "-", "Single": "--"}, str(drawn.get("styles")))
    check("no markers on either", set((drawn.get("markers") or {}).values()) <= {"None", "", None},
          str(drawn.get("markers")))
    check("headroom above the peak for the legend", drawn.get("ytop", 0) > 1.15, str(drawn.get("ytop")))

    print("\n== on a small figure the legend still clears the curves ==")
    seen = {}

    def spy2(fig, *a, **kw):
        ax = fig.axes[0]
        leg = ax.get_legend().get_window_extent().transformed(ax.transData.inverted())
        worst = max((float(y) for ln in ax.get_lines() for x, y in zip(ln.get_xdata(), ln.get_ydata())
                     if leg.x0 <= float(x) <= leg.x1), default=0.0)
        seen["gap"] = leg.y0 - worst
        return real_savefig(fig, *a, **kw)

    plt.Figure.savefig = spy2
    try:
        # The furan overlay's shape: a narrow peak at the legend's left edge,
        # on a 6 x 4 in figure with a wrapped title.
        x = np.linspace(5.2, 9.3, 2000)
        broad = np.exp(-0.5 * ((x - 6.17) / 0.2) ** 2) + 0.74 * np.exp(-0.5 * ((x - 8.1) / 0.25) ** 2)
        narrow = np.exp(-0.5 * ((x - 6.46) / 0.07) ** 2)
        with tempfile.TemporaryDirectory() as tmp:
            render_line_plot(list(x), {"Nuclear ensemble (100 samples)": list(broad / broad.max()),
                                       "Single geometry": list(narrow)}, "Energy (eV)",
                             "Normalized intensity", title, str(Path(tmp) / "s.png"),
                             style=PlotStyle(figsize=(6, 4)), series_styles={"Single geometry": "--"})
    finally:
        plt.Figure.savefig = real_savefig
    check("no curve reaches the legend's lower edge", seen.get("gap", -1) > 0, str(seen))

    print("\n== 'y from 0' pins the floor only, and the legend still clears ==")
    # The round-3 thesis overlay: asked for "y axis starting at 0", the model
    # wrote ylim [0, 1], which fixed the top at the peaks and left the
    # legend on both. One end may now be null.
    check("[0, null] is accepted", from_spec({"look": {"ylim": [0, None]}}).ylim == (0.0, None))
    for bad, label in (({"ylim": [None, None]}, "an axis limit with neither end"),
                       ({"figsize": [6, None]}, "a figsize with a null")):
        try:
            from_spec({"look": bad})
            check(f"{label} is refused", False)
        except PlotStyleError as e:
            check(f"{label} is refused", True, str(e))
    for look, want in (({"ylim": [0, None]}, "open"), ({"ylim": [0, 1]}, "fixed")):
        seen.clear()

        def spy3(fig, *a, **kw):
            ax = fig.axes[0]
            leg = ax.get_legend().get_window_extent().transformed(ax.transData.inverted())
            worst = max((float(y) for ln in ax.get_lines() for x, y in zip(ln.get_xdata(), ln.get_ydata())
                         if leg.x0 <= float(x) <= leg.x1), default=0.0)
            seen["gap"], seen["ylim"] = leg.y0 - worst, ax.get_ylim()
            return real_savefig(fig, *a, **kw)

        plt.Figure.savefig = spy3
        try:
            with tempfile.TemporaryDirectory() as tmp:
                render_line_plot(list(x), {"Nuclear ensemble (100 samples)": list(broad / broad.max()),
                                           "Single geometry": list(narrow)}, "Energy (eV)",
                                 "Normalised intensity", None, str(Path(tmp) / "s.png"),
                                 style=from_spec({"look": {"figsize": [6, 4], **look}}),
                                 series_styles={"Single geometry": "--"})
        finally:
            plt.Figure.savefig = real_savefig
        if want == "open":
            check("open top: the floor stays at 0", abs(seen["ylim"][0]) < 1e-9, str(seen))
            check("open top: no curve reaches the legend", seen.get("gap", -1) > 0, str(seen))
        else:
            check("a fixed range is kept exactly", tuple(round(v, 9) for v in seen["ylim"]) == (0.0, 1.0), str(seen))

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
