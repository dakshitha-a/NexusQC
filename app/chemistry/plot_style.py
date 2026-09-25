"""One style vocabulary, shared by every renderer in app/chemistry/spectrum.py.

Before this, four of the eight plot kinds could not be restyled at all, and it
was not a missing spec key -- it was missing renderer parameters:

    render_uvvis_plot(energies_eV, oscillator_strengths, fwhm_eV, out_path)
    render_ir_spectrum_plot(frequencies_cm1, ir_intensities_km_mol, fwhm_cm1, out_path)
    render_wigner_ensemble_spectrum(pooled_e, pooled_f, pooled_idx, fwhm_eV, out_path, ...)
    render_pes_plot(coordinate_values, state_energies_hartree, coordinate_label, out_path)

None of them accepted a title, a label, a colour or a size; their titles were
f-strings baked into the function bodies. So `plot(kind="edit")` refused them
outright, and "rename the title of my UV/Vis spectrum" -- about as ordinary a
request as this app receives -- was impossible. Everything else that might be
changed (figure size, dpi, fonts, legend position, grid, axis limits, marker
shape and size, line style, output format) was a module-level constant or an
import-time `plt.rcParams.update`, reachable by no caller.

Two decisions worth keeping:

**Font and figure settings are applied per plot, through `rc_context`, not by
mutating `plt.rcParams`.** The old global update ran once at import and set the
look of every figure the process would ever draw. That is fine when there is one
look and wrong the moment a caller asks for a bigger font on one chart, because
a global mutation would silently restyle everyone else's next render too, in a
long-lived server process shared by every user.

**The defaults reproduce exactly what these plots looked like before.** An
unstyled render is unchanged, which is what makes this safe to put underneath
renderers whose output people already have saved.

The vocabulary is not spelled out in `plot`'s docstring, because the tool
surface is measured against a hard budget (tests/backend/agent_01_token_budget.py)
and paying ~40 key names on every ReAct iteration to support a request that
arrives occasionally is the same trade `submit_job`'s 35 flat optionals lost.
One line there names the categories; an unknown key is refused here, naming
what is valid, so the full list is paid only when someone needs it.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Optional

# Okabe-Ito minus its pale yellow, the same order render_series_plot has always
# used. Named here so a caller can ask for a different palette by passing one.
DEFAULT_PALETTE = (
    "#0072B2", "#D55E00", "#009E73", "#CC79A7",
    "#E69F00", "#56B4E9", "#8C564B", "#404040",
)

EXPORT_FORMATS = ("png", "svg", "pdf")


# The four specific text sizes as multiples of the base `font_size`, written
# as the division that produced them so the original absolute defaults
# (16/14/12/12 against a 13pt base) are still legible here. A caller who names
# one of the four gets exactly that number; everyone else scales with the base.
_SIZE_RATIOS = {
    "title_size": 16.0 / 13.0,
    "label_size": 14.0 / 13.0,
    "tick_size": 12.0 / 13.0,
    "legend_size": 12.0 / 13.0,
}


class PlotStyleError(ValueError):
    """A style key or value the vocabulary does not define.

    Carries a message that names what IS valid, so the caller can correct
    itself in one step rather than guessing a second time.
    """


@dataclass
class PlotStyle:
    """Everything about how a plot looks, separate from what it shows."""

    # Text. None means "whatever the renderer would have said", which is how a
    # baked-in title becomes an overridable default instead of a fixed string.
    title: Optional[str] = None
    xlabel: Optional[str] = None
    ylabel: Optional[str] = None

    # Figure
    figsize: tuple = (8.0, 6.0)
    dpi: int = 300
    fmt: str = "png"

    # Type. `font_size` is the BASE, and the four specific sizes are None
    # until someone sets one, meaning "derived from the base by the ratio
    # this project has always used". They used to be four absolute defaults
    # sitting beside it, and every one of them is an rcParam that overrides
    # `font.size` for the text it governs -- so "make the font bigger" set
    # font_size, the four overrides stayed at 16/14/12/12, and the title,
    # the axis labels, the ticks and the legend all came back exactly the
    # size they were. The plot re-rendered looking identical, which is the
    # one failure this whole module exists to prevent.
    font_size: float = 13.0
    title_size: Optional[float] = None
    label_size: Optional[float] = None
    tick_size: Optional[float] = None
    legend_size: Optional[float] = None

    # Axes
    grid: bool = False
    xlim: Optional[tuple] = None
    ylim: Optional[tuple] = None
    log_y: bool = False
    invert_x: bool = False

    # Marks. `palette` is None until a caller sets one, so a renderer with a
    # single accent colour of its own can tell "nobody asked" from "somebody
    # asked for exactly the default order" and keep its own look unchanged.
    palette: Optional[tuple] = None
    # None means "the renderer's own". Each renderer had its own considered
    # value -- a levels tick is 2.5pt because it has to read as a level and
    # not a line, an ensemble's total curve is 2.0pt because it sits over
    # dotted per-state overlays -- and collapsing those onto one number would
    # have quietly restyled plots nobody asked to change.
    line_width: Optional[float] = None
    line_style: str = "-"
    marker: Optional[str] = None
    marker_size: Optional[float] = None

    # Legend: None keeps the renderer's own decision, False turns it off, a
    # string is a matplotlib location, and "outside" puts it beside the axes
    # rather than over the data -- see `place_legend`.
    legend: Any = None

    # Text placed on the plot at a data point, each a validated dict (see
    # `_parse_annotations`). Drawn by `apply`, which every renderer ends
    # with, so one implementation annotates all thirteen plot kinds.
    annotations: tuple = ()

    def with_defaults(self, title=None, xlabel=None, ylabel=None) -> "PlotStyle":
        """Fill in the renderer's own text for anything the caller left unset."""
        return replace(
            self,
            title=self.title if self.title is not None else title,
            xlabel=self.xlabel if self.xlabel is not None else xlabel,
            ylabel=self.ylabel if self.ylabel is not None else ylabel,
        )

    def size(self, name: str) -> float:
        """One text size: the caller's if they named it, else scaled off
        `font_size` by this project's own ratio.

        Rounded to two places because the ratios are stored as the division
        that produced them, and 13 * (16/13) is 16.000000000000004 in
        binary floating point. An unstyled figure has to come back with the
        same numbers it always had, not ones that differ in the last bit.
        """
        explicit = getattr(self, name)
        if explicit is not None:
            return float(explicit)
        return round(self.font_size * _SIZE_RATIOS[name], 2)

    def rc(self) -> dict:
        """The rcParams for one figure, for use with `plt.rc_context`."""
        return {
            "font.size": self.font_size,
            "axes.titlesize": self.size("title_size"),
            "axes.labelsize": self.size("label_size"),
            "xtick.labelsize": self.size("tick_size"),
            "ytick.labelsize": self.size("tick_size"),
            "legend.fontsize": self.size("legend_size"),
        }

    def apply(self, ax, legend_default: bool = False) -> None:
        """Text, limits, grid and legend, after the marks are drawn.

        Called at the end of a renderer rather than the start, because axis
        limits have to win over whatever autoscaling the marks caused.
        """
        if self.title:
            ax.set_title(self.title)
        if self.xlabel:
            ax.set_xlabel(self.xlabel)
        if self.ylabel:
            ax.set_ylabel(self.ylabel)
        if self.log_y:
            ax.set_yscale("log")
        if self.grid:
            ax.grid(True, alpha=0.3, linewidth=0.6)
        if self.xlim:
            ax.set_xlim(*self.xlim)
        elif self.invert_x:
            lo, hi = ax.get_xlim()
            ax.set_xlim(max(lo, hi), min(lo, hi))
        if self.ylim:
            ax.set_ylim(*self.ylim)
        if self.annotations:
            self.draw_annotations(ax)

        want = legend_default if self.legend is None else bool(self.legend)
        if want and ax.get_legend_handles_labels()[0]:
            self.place_legend(ax)

    # `legend: "outside"` is not a matplotlib location. It is spelled out here
    # because matplotlib has no location that means "not over the data": every
    # one of its nine corners is inside the axes, and on a spectrum with a
    # peak near the top there is no free corner at all. Asking for a legend
    # outside the frame is an ordinary request and had no way to be expressed.
    OUTSIDE = "outside"

    def place_legend(self, ax, handles=None) -> None:
        """Draw the legend where the caller asked, handling `outside`."""
        kwargs = {"handles": handles} if handles else {}
        if self.legend == self.OUTSIDE:
            ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0),
                      borderaxespad=0.0, frameon=False, **kwargs)
            return
        ax.legend(loc=self.legend if isinstance(self.legend, str) else "upper right", **kwargs)

    def reserve_legend_headroom(self, ax, n_entries: int) -> None:
        """Make room above the data for a legend before drawing it.

        `render_series_plot` has always done this and the spectrum renderers
        never did, so a UV/Vis or IR legend sat on the peak -- invisibly at
        the default 13pt, and unmissably once somebody set `font_size: 22`,
        which is the request that turned it up. Skipped when the caller set an
        explicit ylim, which is theirs, and when the legend is outside the
        axes, where there is nothing to make room for.
        """
        if self.ylim is not None or self.legend in (False, self.OUTSIDE):
            return
        bottom, top = ax.get_ylim()
        if self.log_y:
            # Headroom is a multiple on a log axis, not an addition: adding a
            # fraction of the range there is dominated by the largest value
            # and buys almost no room in the top decade.
            ax.set_ylim(bottom, top * (10 ** (0.04 + 0.05 * n_entries)))
        else:
            ax.set_ylim(bottom, top + (top - bottom) * (0.06 + 0.07 * n_entries))

    def draw_annotations(self, ax) -> None:
        """Place each annotation at its data point.

        A text `x` names a category and is looked up among the axis's tick
        labels, by the full label or by its first line, so "CASSCF (BAGEL)"
        still finds a label that carries a second line under it. A number is
        a data coordinate, which on a category axis is the slot index. A text
        `x` on a numeric axis is refused rather than guessed at, and so is a
        category that is not on the axis, naming the ones that are.

        The top of the axis is raised to fit an annotation that would sit
        above it, unless the caller fixed `ylim`, which is theirs.
        """
        categories = _category_positions(ax)
        bottom, top = ax.get_ylim()
        highest = top
        for note in self.annotations:
            x = note["x"]
            if isinstance(x, str):
                if categories is None:
                    raise PlotStyleError(
                        f"annotation x {x!r} names a category, but this plot's x axis is "
                        f"numeric. Give x as a number on that axis.")
                position = categories.get(x.strip())
                if position is None:
                    raise PlotStyleError(
                        f"annotation x {x!r} is not a column of this plot. The columns are: "
                        f"{', '.join(repr(k) for k in _unique_first_lines(categories))}.")
                x = position
            elif categories is not None:
                # A number on a category axis names the column whose label is
                # that number when there is one ("3" among "1".."5", or 1.1 on
                # a levels chart over a scan), and is a slot index otherwise.
                x = _numeric_label_position(categories, x)
            arrow = bool(note.get("arrow"))
            dx, dy = note.get("offset") or ((0.0, 26.0) if arrow else (0.0, 5.0))
            color = note.get("color") or "#222222"
            ax.annotate(
                note["text"], xy=(x, note["y"]), xytext=(dx, dy), textcoords="offset points",
                ha="center", va="bottom" if dy >= 0 else "top",
                fontsize=note.get("size") or self.size("tick_size"), color=color,
                arrowprops={"arrowstyle": "->", "color": color, "lw": 1.0} if arrow else None,
            )
            highest = max(highest, note["y"])
        if self.ylim is None and not self.log_y and highest >= top - 0.08 * (top - bottom):
            ax.set_ylim(bottom, highest + 0.12 * (top - bottom))

    def color(self, index: int, override: Optional[str] = None) -> str:
        """The colour for series `index`, in a multi-series chart."""
        palette = self.palette or DEFAULT_PALETTE
        return override or palette[index % len(palette)]

    def accent(self, default: str) -> str:
        """The single accent colour of a one-series chart.

        Renderers that draw one curve have their own accent ("tab:blue" for a
        spectrum, "#3b6fd6" for a histogram) which is not a categorical scale
        and should not be swapped for the first entry of one. So the caller's
        palette wins only if they actually set one.
        """
        return self.palette[0] if self.palette else default

    def cycle_color(self, index: int):
        """Colour for series `index`, or None to leave matplotlib's own cycle.

        `render_line_plot` never set colours; it let matplotlib walk its
        default cycle. Forcing a palette on it would have changed every scan
        and optimization plot already saved, so None stays None here.
        """
        return self.palette[index % len(self.palette)] if self.palette else None

    def lw(self, default: float) -> float:
        """Line width: the caller's if they set one, else this renderer's."""
        return self.line_width if self.line_width is not None else default

    def ms(self, default: float) -> float:
        """Marker size: the caller's if they set one, else this renderer's."""
        return self.marker_size if self.marker_size is not None else default


# Every key `from_spec` accepts, with the coercion each one needs. Kept as data
# so the refusal message and the parser cannot disagree about what is valid.
_COERCE = {
    "title": str, "xlabel": str, "ylabel": str,
    "dpi": int, "fmt": str,
    "font_size": float, "title_size": float, "label_size": float,
    "tick_size": float, "legend_size": float,
    "grid": bool, "log_y": bool, "invert_x": bool,
    "line_width": float, "line_style": str, "marker": str, "marker_size": float,
}
_PAIRS = ("figsize", "xlim", "ylim")

STYLE_KEYS = tuple(sorted(list(_COERCE) + list(_PAIRS) + ["palette", "legend"]))


ANNOTATION_KEYS = ("arrow", "color", "offset", "size", "text", "x", "y")


def _parse_annotations(raw) -> tuple:
    """Validate `spec["annotations"]` into a tuple of plain dicts.

    Refuses a malformed entry by name, for the same reason an unknown style
    key is refused: an annotation that is accepted and quietly not drawn is
    the exact failure that made this feature necessary. On 2026-09-24 the
    agent sent a well-formed list, the app had nowhere to put it, and the
    plot came back unchanged while the user asked where the labels were.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PlotStyleError("'annotations' must be a list of {\"text\", \"x\", \"y\"} objects.")
    out = []
    for i, entry in enumerate(raw):
        where = f"annotation {i + 1}"
        if not isinstance(entry, dict):
            raise PlotStyleError(f"{where} must be an object like {{\"text\": \"5.13\", \"x\": 0, \"y\": 5.13}}.")
        unknown = sorted(k for k in entry if k not in ANNOTATION_KEYS)
        if unknown:
            raise PlotStyleError(f"{where} has unknown key(s) {', '.join(unknown)}. "
                                 f"Valid keys are: {', '.join(ANNOTATION_KEYS)}.")
        text, x, y = entry.get("text"), entry.get("x"), entry.get("y")
        if text is None or str(text) == "":
            raise PlotStyleError(f"{where} needs 'text'.")
        if isinstance(x, bool) or not isinstance(x, (int, float, str)):
            raise PlotStyleError(f"{where} needs 'x': a number on the x axis, or a column's label.")
        try:
            y = float(y)
        except (TypeError, ValueError):
            raise PlotStyleError(f"{where} needs 'y' as a number on the y axis; got {y!r}.")
        note = {"text": str(text), "x": x if isinstance(x, str) else float(x), "y": y,
                "arrow": bool(entry.get("arrow", False))}
        if entry.get("color") is not None:
            note["color"] = str(entry["color"])
        if entry.get("offset") is not None:
            note["offset"] = _pair(f"{where} offset", entry["offset"])
        if entry.get("size") is not None:
            try:
                note["size"] = float(entry["size"])
            except (TypeError, ValueError):
                raise PlotStyleError(f"{where} 'size' must be a number of points.")
        out.append(note)
    return tuple(out)


def _category_positions(ax) -> Optional[dict]:
    """{label: x position} for a category axis, or None for a numeric one.

    Decided by the axis's formatter, never by what the labels say. A category
    axis can carry labels that read as numbers: a single job's slots are
    labelled "1".."n", and a levels chart over a scan coordinate is labelled
    "0.90", "1.00" and so on. Judged by text, those looked numeric, so a
    column named "3" was refused and x=2 landed on the slot labelled "3".

    Two ways a renderer makes a category axis. `set_xticklabels`
    (`_apply_categorical_xticks`, the thermochemistry chart) installs a
    FuncFormatter in matplotlib 3.11 and a FixedFormatter before it; no
    renderer here installs either for any other reason. Plotting strings
    directly gives matplotlib's own category units. A numeric axis carries a
    ScalarFormatter or one of the LogFormatters. Each label is registered
    under its full text and under its first line.
    """
    from matplotlib.ticker import FixedFormatter, FuncFormatter

    pairs: list = []
    mapping = getattr(getattr(ax.xaxis, "units", None), "_mapping", None)
    if mapping:
        pairs = list(mapping.items())
    elif isinstance(ax.xaxis.get_major_formatter(), (FuncFormatter, FixedFormatter)):
        pairs = list(zip([t.get_text() for t in ax.get_xticklabels()], ax.get_xticks()))
    if not pairs:
        return None
    positions: dict = {}
    for label, position in pairs:
        label = str(label)
        for key in (label.strip(), label.split("\n", 1)[0].strip()):
            positions.setdefault(key, float(position))
    return positions


def _numeric_label_position(categories: dict, x: float) -> float:
    for label, position in categories.items():
        try:
            if abs(float(label.replace("\u2212", "-")) - x) < 1e-9:
                return position
        except ValueError:
            continue
    return x


def _unique_first_lines(categories: dict) -> list:
    """The first-line keys, once each, for naming the columns in a refusal."""
    return list(dict.fromkeys(k.split("\n", 1)[0] for k in categories))


def _pair(name: str, value) -> tuple:
    try:
        lo, hi = value
        return (float(lo), float(hi))
    except (TypeError, ValueError):
        raise PlotStyleError(f"style '{name}' wants two numbers, e.g. [0, 10]; got {value!r}.")


def from_spec(spec: Optional[dict]) -> PlotStyle:
    """Build a PlotStyle from a plot spec's `style` block.

    Refuses an unknown key by name rather than ignoring it. Silently dropping
    it would be worse than an error here: the plot would re-render looking
    exactly the same, and the only available reading of that is that the app
    ignored the request.
    """
    spec = spec or {}
    raw = spec.get("look")
    if raw is None:
        # `spec["style"]` already means the MARK for a custom plot -- the
        # string "line", "scatter", "bar" or "levels". The appearance block is
        # `look`, but "style" is the word anyone reaches for first, so a
        # dict-valued "style" is read as appearance and a string one is left
        # to mean the mark. The two cannot be confused: they are different
        # types, and no mark is an object.
        candidate = spec.get("style")
        raw = candidate if isinstance(candidate, dict) else {}
    if not isinstance(raw, dict):
        raise PlotStyleError("'look' must be an object of style keys, e.g. {\"title\": \"...\"}.")

    # Annotations live at the top of the spec. Written inside `look` they
    # are read from there too, rather than refused as an unknown style key:
    # they are drawn either way, and the one outcome ruled out is a list that
    # is accepted and not drawn.
    raw = dict(raw)
    annotations = _parse_annotations(
        spec.get("annotations") if spec.get("annotations") is not None else raw.pop("annotations", None))
    raw.pop("annotations", None)

    unknown = [k for k in raw if k not in STYLE_KEYS]
    if unknown:
        raise PlotStyleError(
            f"Unknown style key(s): {', '.join(sorted(unknown))}. "
            f"Valid keys are: {', '.join(STYLE_KEYS)}."
        )

    kwargs: dict = {}
    for key, value in raw.items():
        if value is None:
            continue
        if key in _PAIRS:
            kwargs[key] = _pair(key, value)
        elif key == "palette":
            colors = tuple(str(c) for c in value) if isinstance(value, (list, tuple)) else ()
            if not colors:
                raise PlotStyleError("style 'palette' wants a list of colours, e.g. [\"#0072B2\", \"#D55E00\"].")
            kwargs[key] = colors
        elif key == "legend":
            # True/False or a matplotlib location string, both meaningful.
            kwargs[key] = value if isinstance(value, (str, bool)) else bool(value)
        else:
            try:
                kwargs[key] = _COERCE[key](value)
            except (TypeError, ValueError):
                raise PlotStyleError(
                    f"style '{key}' could not be read as {_COERCE[key].__name__}: {value!r}."
                )

    fmt = kwargs.get("fmt")
    if fmt and fmt.lower() not in EXPORT_FORMATS:
        raise PlotStyleError(f"style 'fmt' must be one of {', '.join(EXPORT_FORMATS)}; got {fmt!r}.")
    # `fmt` was in this vocabulary from the start and nothing read it: the
    # store wrote `<version>.png` and the routes served and named a PNG, so
    # asking for SVG produced a PNG under a PNG name with no complaint. It was
    # briefly refused outright, as the honest reading of that; it works now.
    # A vector is rendered ALONGSIDE the PNG rather than instead of it (see
    # app/plots/store.py's add_version), because the panel and the chat bubble
    # display a version in an <img> and a PDF cannot be shown that way. So
    # `fmt` decides what a download hands over, not what the app displays.
    if fmt:
        kwargs["fmt"] = fmt.lower()

    return PlotStyle(annotations=annotations, **kwargs)


# --------------------------------------------------------------------------
# R-079. One lock around every figure this app draws.
#
# Every renderer in app/chemistry/spectrum.py and app/chemistry/job_charts.py
# uses the pyplot state machine: `plt.rc_context(...)` mutates a global
# rcParams dict for the duration of a block, and `plt.subplots()` registers
# the figure in a global manager. Matplotlib documents pyplot as not
# thread-safe, and these renderers are called from FastAPI's request
# threadpool and from the orchestrator threads, so two renders genuinely can
# overlap. When they do, one figure is drawn under the other's rcParams: wrong
# fonts, wrong sizes, wrong colours. This project treats a chart as a
# scientific artifact rather than decoration, so a chart that is quietly drawn
# in someone else's style is a real defect even though no number in it is
# wrong. `plt.subplots`'s global registration also means a crash mid-render
# can leak a figure.
#
# A single process-wide lock rather than one per module, because the state
# being protected is one global. It is held only for the draw itself, which is
# on the order of a tenth of a second, so concurrent plot requests queue
# briefly rather than colliding. The alternative, moving every renderer to the
# object-oriented `Figure()` plus `FigureCanvasAgg` API with an explicit
# rcParams dict, needs no global state at all and is the better end state; it
# is also a rewrite of thirteen renderers, and this is the change that makes
# the current ones correct.
_render_lock = threading.Lock()


@contextmanager
def figure_lock():
    """Hold while creating and drawing a pyplot figure. See above.

    A render that raises closes every open figure on the way out. Before
    annotations, a renderer raised only on a real fault; now a refused
    annotation (a column that is not on the axis) raises from inside
    `apply`, after the figure exists and before the renderer's own
    `plt.close`, and the figure would stay registered in pyplot for the
    life of the server. Closing "all" is safe only because this lock
    serialises rendering, so the one open figure is the failing one.
    """
    with _render_lock:
        try:
            yield
        except BaseException:
            import matplotlib.pyplot as plt  # already imported by whichever renderer raised
            plt.close("all")
            raise
