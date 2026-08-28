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

from dataclasses import dataclass, replace
from typing import Any, Optional

# Okabe-Ito minus its pale yellow, the same order render_series_plot has always
# used. Named here so a caller can ask for a different palette by passing one.
DEFAULT_PALETTE = (
    "#0072B2", "#D55E00", "#009E73", "#CC79A7",
    "#E69F00", "#56B4E9", "#8C564B", "#404040",
)

EXPORT_FORMATS = ("png", "svg", "pdf")


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

    # Type
    font_size: float = 13.0
    title_size: float = 16.0
    label_size: float = 14.0
    tick_size: float = 12.0
    legend_size: float = 12.0

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
    # string is a matplotlib location.
    legend: Any = None

    def with_defaults(self, title=None, xlabel=None, ylabel=None) -> "PlotStyle":
        """Fill in the renderer's own text for anything the caller left unset."""
        return replace(
            self,
            title=self.title if self.title is not None else title,
            xlabel=self.xlabel if self.xlabel is not None else xlabel,
            ylabel=self.ylabel if self.ylabel is not None else ylabel,
        )

    def rc(self) -> dict:
        """The rcParams for one figure, for use with `plt.rc_context`."""
        return {
            "font.size": self.font_size,
            "axes.titlesize": self.title_size,
            "axes.labelsize": self.label_size,
            "xtick.labelsize": self.tick_size,
            "ytick.labelsize": self.tick_size,
            "legend.fontsize": self.legend_size,
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

        want = legend_default if self.legend is None else bool(self.legend)
        if want and ax.get_legend_handles_labels()[0]:
            loc = self.legend if isinstance(self.legend, str) else "upper right"
            ax.legend(loc=loc)

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
    if fmt:
        kwargs["fmt"] = fmt.lower()

    return PlotStyle(**kwargs)
