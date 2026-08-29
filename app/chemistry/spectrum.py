"""Gaussian-broadened UV/Vis absorption spectrum rendering from discrete
excitation energies + oscillator strengths, as reported in a completed
tddft/eom_ccsd/casscf(want_oscillator_strengths=True) job summary."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless -- this runs inside a server/agent process, never a display
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

# P9.5: one shared style, applied once at import time, rather than the
# per-call fontsize=7/8 tuning every renderer below used to carry
# individually (and the renderers that carried none at all, silently
# falling back to matplotlib's 10pt default for axis labels/titles). A
# future renderer added to this file inherits this automatically instead
# of needing its own tuning pass. Also matches "every plot downloads as a
# high-resolution 8x6 PNG" (docs/MASTER_PLAN_SUMMARY.md): every renderer
# below shares one figsize/dpi, not the mix of 6.5x4/7x4.5 sizes and one
# dpi some plots had before this.
# These live on PlotStyle now, as its defaults, so a caller can change them
# per plot. The values are unchanged, so an unstyled render is byte-for-byte
# what it was.
#
# They used to be a module-level `plt.rcParams.update(...)` that ran once at
# import and set the look of every figure this process would ever draw. That
# is fine while there is exactly one look and wrong the moment someone asks
# for a bigger font on one chart: a global mutation in a long-lived server
# shared by every user would restyle the next person's plot too. Each
# renderer now opens a `plt.rc_context` for its own figure instead.
from dataclasses import replace  # noqa: E402

from app.chemistry.plot_style import PlotStyle  # noqa: E402

_FIGSIZE = PlotStyle.figsize
_DPI = PlotStyle.dpi

# The one table lives in app/chemistry/units.py; these two names stay so
# the formulas below read as they always did.
from app.chemistry.units import EV_TO_NM as _EV_TO_NM, HARTREE_TO_EV as _HARTREE_TO_EV

# Okabe-Ito, the standard colourblind-safe qualitative order, minus its pale
# yellow (#F0E442), which is close to illegible as a thin line on the white
# background every renderer in this file saves with. Used to colour one series
# per electronic state (or per whatever the caller is comparing) in
# render_series_plot. Deliberately NOT retrofitted onto the single-accent
# "#3b6fd6" renderers below: that colour is one accent, not a categorical
# scale, so swapping it would change existing plots for no accessibility gain.
_CATEGORICAL_COLORS = (
    "#0072B2", "#D55E00", "#009E73", "#CC79A7",
    "#E69F00", "#56B4E9", "#8C564B", "#404040",
)

# Every mark render_series_plot knows how to draw. plot(kind="custom") checks
# a requested style against this rather than carrying its own copy of the list.
SERIES_PLOT_STYLES = ("line", "scatter", "bar", "levels")


def _apply_categorical_xticks(ax, labels: list[str]) -> None:
    """Lay out one tick per category at 0..n-1, rotated far enough to stay
    readable. The fixed rotation=20 the old job-comparison renderer used was
    tuned for a handful of short job names and overlaps badly at, say, seven
    method names of ~13 characters, so the angle scales with how crowded the
    axis actually is. The explicit xlim keeps half a slot of margin at each
    end, which
    matters for "levels" and "bar": both draw marks with real width around
    their position, and matplotlib's autoscaling would otherwise clip the
    first and last ones."""
    ax.set_xticks(range(len(labels)))
    longest = max((len(label) for label in labels), default=0)
    rotation = 35 if (len(labels) > 4 or longest > 18) else 20
    ax.set_xticklabels(labels, rotation=rotation, ha="right")
    ax.set_xlim(-0.6, len(labels) - 0.4)


def render_series_plot(
    positions: list[float], tick_labels: list[str] | None, series: list[dict],
    xlabel: str, ylabel: str, title: str, out_path: str,
    style: str = "line", log_y: bool = False, plot_style: PlotStyle = None,
) -> None:
    """The one renderer behind plot(kind="custom") and plot(kind="comparison").
    Four marks over one data shape, so a new chart the user describes is a
    different `style` rather than a different function.

    `series` is a LIST of dicts ({"label", "values", optional "color"}) rather
    than render_line_plot's dict-of-lists: order is the legend order and the
    colour order, an explicit per-series colour has somewhere to live, and two
    series that happen to share a label cannot silently collapse into one.

    `tick_labels` is what picks the axis kind. None means `positions` are real
    numbers on a numeric axis (a bond length, a scan coordinate). A list means
    they are 0..n-1 slots labelled with these strings, which is what "compare
    these methods" needs and what render_line_plot could not express.

    A `None` in a series' values is a gap, never a dropped column: the mark is
    simply absent at that slot and the category keeps its tick and its label.
    That is the point of the whole convention -- a job with no oscillator
    strengths should show up as a labelled column with nothing in it, not
    vanish from a seven-method comparison as though it had never been run.

    `style` is the MARK (line/scatter/bar/levels); `plot_style` is how the
    whole figure looks. Two different words because they are two different
    things and this function needs both.
    """
    if style not in SERIES_PLOT_STYLES:
        raise ValueError(f"unknown series plot style {style!r}")

    st = (plot_style or PlotStyle()).with_defaults(title=title, xlabel=xlabel, ylabel=ylabel)
    if log_y:
        st = replace(st, log_y=True)

    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        n_series = len(series)
        proxy_handles: list[Line2D] = []

        for i, entry in enumerate(series):
            color = st.color(i, entry.get("color"))
            label = entry["label"]
            y = [np.nan if v is None else float(v) for v in entry["values"]]
            if style == "line":
                ax.plot(positions, y, marker=st.marker if st.marker is not None else "o",
                        markersize=st.ms(3.0), linewidth=st.lw(1.5),
                        linestyle=st.line_style, color=color, label=label)
            elif style == "scatter":
                # s is an AREA in points squared, while marker_size is a
                # diameter in points, as everywhere else in this file. The
                # default 3.0 reproduces the old fixed s=36.
                ax.scatter(positions, y, s=st.ms(3.0) ** 2 * 4,
                           marker=st.marker or "o", color=color, label=label)
            elif style == "bar":
                # Grouped bars: the full slot is 0.8 wide, shared evenly, centred
                # on the position so a single series still sits over its tick.
                width = 0.8 / n_series
                offset = (i - (n_series - 1) / 2) * width
                ax.bar([p + offset for p in positions], y, width=width, color=color, label=label)
            else:  # "levels" -- an energy-level diagram: a short horizontal tick per value
                for p, v in zip(positions, y):
                    if not np.isnan(v):
                        ax.hlines(v, p - 0.30, p + 0.30, color=color,
                                  linewidth=st.lw(2.5))
                # hlines returns a fresh LineCollection per call, so labelling them
                # would put one legend entry per drawn segment. A proxy handle gives
                # exactly one entry per series, and gives it even when every value
                # in that series is a gap -- the legend should still say the state
                # was asked for and had nothing to show.
                proxy_handles.append(Line2D([0], [0], color=color,
                                            linewidth=st.lw(2.5), label=label))

        if tick_labels is not None:
            _apply_categorical_xticks(ax, tick_labels)

        want_legend = (n_series > 1) if st.legend is None else bool(st.legend)
        if want_legend and st.ylim is None:
            # Reserve room above the data for the legend before drawing it.
            # matplotlib's loc="best" places a legend by looking at the artists it
            # knows how to measure, and it does not measure LineCollections, which
            # is exactly what "levels" draws -- so the legend cheerfully covered
            # the highest level in a seven-method comparison. Making the headroom
            # explicit fixes every style rather than only that one, and it is
            # applied before the legend so autoscaling cannot undo it. Skipped
            # when the caller set an explicit ylim, which is theirs to decide.
            bottom, top = ax.get_ylim()
            if st.log_y:
                # Headroom is a multiple on a log axis, not an addition. Adding a
                # fraction of (top - bottom) there is dominated by the largest
                # value and buys almost no visual room near the top decade.
                ax.set_ylim(bottom, top * (10 ** (0.04 + 0.05 * n_series)))
            else:
                ax.set_ylim(bottom, top + (top - bottom) * (0.06 + 0.07 * n_series))

        # Title, labels, log scale, grid and any explicit limits, after the
        # headroom above so a caller's ylim still wins.
        st.apply(ax, legend_default=False)
        if want_legend:
            loc = st.legend if isinstance(st.legend, str) else "upper right"
            ax.legend(handles=proxy_handles or None, loc=loc)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)


def _broadened_spectrum(
    energies_eV: list[float], oscillator_strengths: list[float], fwhm_eV: float, n_points: int = 2000,
) -> tuple[np.ndarray, np.ndarray]:
    energies = np.asarray(energies_eV, dtype=float)
    osc = np.asarray(oscillator_strengths, dtype=float)
    sigma = fwhm_eV / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    lo = max(0.5, float(energies.min()) - 5 * sigma)
    hi = float(energies.max()) + 5 * sigma
    grid_eV = np.linspace(lo, hi, n_points)
    spectrum = np.zeros_like(grid_eV)
    for e, f in zip(energies, osc):
        spectrum += f * np.exp(-0.5 * ((grid_eV - e) / sigma) ** 2)
    return grid_eV, spectrum


def render_line_plot(
    x: list[float], y_series: dict[str, list[float | None]], xlabel: str, ylabel: str, title: str, out_path: str,
    log_y: bool = False, style: PlotStyle = None,
) -> None:
    """Shared publication-style (white background, real ticks, legend when
    there's more than one series) matplotlib line plot -- one line per
    dict entry in y_series, `None` entries plotted as gaps (a failed
    pes_scan image, see render_pes_plot) rather than interpolated across
    or silently dropped. Used for pes_scan's energy-vs-coordinate plot and
    reused for the on-demand PNG-download rendering of the existing
    frontend-only optimization-energy/UV-Vis-inline charts (see
    server/routes/jobs.py's render_plot route), and for plot(kind="custom")'s
    declarative series (app/agent/tools.py)."""
    st = (style or PlotStyle()).with_defaults(title=title, xlabel=xlabel, ylabel=ylabel)
    if log_y:
        st = replace(st, log_y=True)
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        for i, (label, y) in enumerate(y_series.items()):
            y_masked = [v if v is not None else np.nan for v in y]
            ax.plot(x, y_masked, marker=st.marker if st.marker is not None else "o",
                    markersize=st.ms(3.0), linewidth=st.lw(1.5),
                    linestyle=st.line_style, color=st.cycle_color(i), label=label)
        st.apply(ax, legend_default=len(y_series) > 1)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)




def render_pes_plot(
    coordinate_values: list[float], state_energies_hartree: dict[str, list[float | None]],
    coordinate_label: str, out_path: str, style: PlotStyle = None,
) -> None:
    """PES scan plot -- one line per electronic state, in relative energy
    (eV, referenced to the lowest known energy across every state/image so
    multiple states share one consistent zero), image indices with no
    successful energy plotted as a gap (see JobResult in
    app/chemistry/jobs/scan_orchestrator.py's "completed with gaps"
    handling of a partially-failed scan)."""
    known = [v for series in state_energies_hartree.values() for v in series if v is not None]
    if not known:
        raise ValueError("No successful images to plot -- every sub-job in this scan failed")
    zero = min(known)
    relative = {
        label: [(v - zero) * _HARTREE_TO_EV if v is not None else None for v in series]
        for label, series in state_energies_hartree.items()
    }
    render_line_plot(
        coordinate_values, relative, coordinate_label, "Relative energy (eV)",
        "Potential energy scan", out_path, style=style,
    )


def render_neb_plot(path_rows: list[dict], out_path: str, style: PlotStyle = None) -> None:
    """neb_ts reaction-path plot (see orca_runner.run_neb_ts's
    _neb_path_summary for path_rows' shape). A separate function rather
    than a render_line_plot call, since the TS point (when present) needs
    a genuinely different visual encoding from the numbered path line, not
    just another series in the same dict: it has no real x-coordinate of
    its own (the TS-optimization step moves off the climbing image's exact
    position), so it's drawn as a distinct marker at the climbing image's
    index (the row marked "<= CI" by ORCA) rather than inventing a
    fractional x position or silently omitting it."""
    numbered = [r for r in path_rows if r["image"] != "TS"]
    if not numbered:
        raise ValueError("No numbered path images to plot")
    ts_rows = [r for r in path_rows if r["image"] == "TS"]
    zero = min(r["energy_hartree"] for r in numbered + ts_rows)

    xs = [int(r["image"]) for r in numbered]
    ys = [(r["energy_hartree"] - zero) * _HARTREE_TO_EV for r in numbered]

    st = (style or PlotStyle()).with_defaults(
        title="NEB-TS reaction path", xlabel="Image", ylabel="Relative energy (eV)")
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        ax.plot(xs, ys, marker=st.marker if st.marker is not None else "o",
                markersize=st.ms(4.0), linewidth=st.lw(1.5), linestyle=st.line_style,
                color=st.accent("#3b6fd6"), label="Path")
        if ts_rows:
            ci_row = next((r for r in numbered if r.get("marker") == "CI"), None)
            ts_x = int(ci_row["image"]) if ci_row else xs[len(xs) // 2]
            ts_y = (ts_rows[0]["energy_hartree"] - zero) * _HARTREE_TO_EV
            ax.scatter([ts_x], [ts_y], color="#d6483b", zorder=5, s=70, marker="^",
                       label="TS (refined)")
        st.apply(ax, legend_default=True)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)


_TRANS_ROT_FREQ_CUTOFF_CM1 = 10.0


def render_ir_spectrum_plot(
    frequencies_cm1: list[float], ir_intensities_km_mol: list[float], fwhm_cm1: float, out_path: str,
    style: PlotStyle = None,
) -> None:
    """Gaussian-broadened IR spectrum from a completed frequency job's
    frequencies_cm-1/ir_intensities_km_mol -- ORCA/BAGEL only in this app
    (PySCF's pyscf.hessian.thermo.harmonic_analysis computes no
    dipole-derivative/IR-intensity output at all, see orca_runner.py's and
    bagel_runner.py's run_frequency).

    Modes with |frequency| below _TRANS_ROT_FREQ_CUTOFF_CM1 are dropped
    before broadening/plotting, not just left at their real (always
    exactly 0.0) intensity: both engines keep the 5-6 near-zero projected
    translational/rotational modes in their frequency/intensity lists
    (see orca_runner._FREQ_LINE's and bagel_runner._HESSIAN_FREQ_ROW's own
    comments on why those aren't filtered at parse time), and including a
    frequency of 0.0 in the axis-range calculation below would stretch the
    whole plot to include a dead zone from 0 up to the first real
    vibration, squashing every genuine peak into a sliver of the figure.
    10 cm-1 is comfortably above BAGEL's observed numerical-Hessian
    projection noise (~6 cm-1 on a real run) and comfortably below any
    real vibrational mode for any molecule, including soft torsions.

    ir_intensities_km_mol must already be all-numeric (no None entries) --
    callers (see plot_ir_spectrum in tools.py) are responsible for
    refusing to plot when intensities aren't available at all, matching
    render_uvvis_plot's own contract."""
    pairs = [(f, i) for f, i in zip(frequencies_cm1, ir_intensities_km_mol) if abs(f) >= _TRANS_ROT_FREQ_CUTOFF_CM1]
    if not pairs:
        raise ValueError("No vibrational modes (above the translational/rotational cutoff) to plot")
    freqs = np.array([f for f, _ in pairs])
    ir = np.array([i for _, i in pairs])

    sigma = fwhm_cm1 / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    lo = max(0.0, float(freqs.min()) - 5 * sigma)
    hi = float(freqs.max()) + 5 * sigma
    grid = np.linspace(lo, hi, 2000)
    spectrum = np.zeros_like(grid)
    for f, i in zip(freqs, ir):
        spectrum += i * np.exp(-0.5 * ((grid - f) / sigma) ** 2)

    st = (style or PlotStyle()).with_defaults(
        title=f"IR spectrum (FWHM = {fwhm_cm1:.0f} cm$^{{-1}}$)",
        xlabel="Wavenumber (cm$^{-1}$)",
        ylabel="IR intensity (Gaussian-broadened, km/mol)",
    )
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        ax.plot(grid, spectrum, color=st.accent("tab:blue"),
                linewidth=st.lw(1.5), linestyle=st.line_style,
                marker=st.marker, markersize=st.ms(3.0))
        ax.vlines(freqs, 0, ir, color="tab:gray", alpha=0.6, linewidth=1)
        st.apply(ax)
        # Conventional IR display puts high wavenumber on the left. An
        # explicit xlim from the caller wins; st.apply has already set it.
        if st.xlim is None:
            ax.set_xlim(hi, lo)
        if st.ylim is None:
            ax.set_ylim(bottom=0)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi)
        plt.close(fig)


# The equilibrium marker's red. Deliberately not the histogram's blue and
# not a shade of it: this line is a different KIND of thing from the bars,
# a single known value against a distribution, and it has to read as one
# at a glance.
_EQUILIBRIUM_RED = "#c1272d"


def format_reference_value(value: float) -> str:
    """Three decimals, trailing zeros trimmed -- for a geometric parameter
    shown as a reference value, on a plot or in the reply beside it.

    %.4g reads badly across the three things this labels: a planar ring's
    dihedral comes out of an optimization at -0.0006766 rather than 0, and
    "equilibrium -0.0006766 deg" is noise dressed as precision. Three
    decimals is finer than any of these parameters is meaningful to and
    gives 1.335 A, 120.9 deg and -0.001 deg."""
    if abs(value) >= 1e4:
        return f"{value:.4g}"
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def render_histogram_plot(
    data_by_label: dict[str, list[float]], units_by_label: dict[str, str], out_path: str,
    equilibrium_by_label: dict[str, float] | None = None,
) -> None:
    """One histogram panel per requested geometric parameter, side by side
    in a single image -- for geometry_parameters' (tools.py, P9.2) tagged
    batch/wigner_spectra case: an unordered collection or a statistical
    ensemble of child geometries, where the distribution across every
    sample is the point, not any one member's value. Several panels in
    one PNG rather than one PLOT_ARTIFACT marker per parameter, since
    MessageBubble.tsx's PLOT_ARTIFACT_RE matches exactly one marker per
    tool response (see that regex's own anchoring).

    `equilibrium_by_label` marks a known reference value on a panel as a
    red dashed line, labelled with the number. For a Wigner ensemble that
    is the geometry the normal modes were computed at, which is what the
    samples are displaced AROUND -- a distribution without it shows how
    far the structures spread and not what they spread from, and "where
    was the equilibrium?" is the first thing a reader asks. A label
    missing from the dict simply gets no line, so a panel whose reference
    could not be resolved still draws."""
    labels = list(data_by_label)
    fig, axes = plt.subplots(1, len(labels), figsize=(_FIGSIZE[0] * len(labels), _FIGSIZE[1]))
    if len(labels) == 1:
        axes = [axes]
    for ax, label in zip(axes, labels):
        values = data_by_label[label]
        ax.hist(values, bins="auto", color="#3b6fd6", edgecolor="white")
        unit = units_by_label.get(label, "")
        ax.set_xlabel(f"{label} ({unit})" if unit else label)
        ax.set_ylabel("Count")
        ax.set_title(f"{label} (n={len(values)})")
        equilibrium = (equilibrium_by_label or {}).get(label)
        if equilibrium is not None:
            ax.axvline(equilibrium, color=_EQUILIBRIUM_RED, linestyle="--", linewidth=1.6, zorder=3)
            # Positioned in axes fraction on y so the label sits at the top
            # of the panel whatever the counts are, and rotated so a long
            # number beside a vertical line does not run into the bars or
            # off the edge. Nudged right of the line rather than centred on
            # it, which would put the text over the line itself.
            ax.annotate(
                f"equilibrium {format_reference_value(equilibrium)}" + (f" {unit}" if unit else ""),
                xy=(equilibrium, 0.98), xycoords=ax.get_xaxis_transform(),
                xytext=(5, 0), textcoords="offset points",
                color=_EQUILIBRIUM_RED, fontsize=11, rotation=90, ha="left", va="top",
                # The label lands wherever the equilibrium is, which is
                # usually the middle of the distribution and therefore on
                # top of the tallest bars. Red on the histogram's blue is
                # close to unreadable, so the text carries its own ground.
                bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                          edgecolor="none", alpha=0.85),
            )
    fig.tight_layout()
    fig.savefig(out_path, dpi=_DPI, facecolor="white")
    plt.close(fig)


def render_entropy_plateau_plot(
    entropies: list[float], threshold: float | None, selected_indices: list[int], out_path: str,
    style: PlotStyle = None,
) -> None:
    """Single-orbital entropy, sorted descending, for run_recommend_active_space
    (pyscf_runner.py) -- the auditable evidence behind an autoCAS-style active-
    space recommendation: which pilot orbitals were selected (entropy above
    the plateau threshold) vs not, and where the threshold itself fell.
    threshold is None when no plateau was found (see
    pyscf_runner._find_entropy_plateau) -- plotted without a threshold line
    in that case rather than fabricating one, matching this app's refuse-
    don't-fabricate pattern for plot_excited_state_spectrum/plot_ir_spectrum."""
    order = np.argsort(-np.array(entropies))
    sorted_entropies = [entropies[i] for i in order]
    selected_set = set(selected_indices)
    colors = ["#3b6fd6" if int(i) in selected_set else "#9aa4b2" for i in order]

    st = (style or PlotStyle()).with_defaults(
        title="Active-space selection: single-orbital entropy"
              + ("" if threshold is not None else " (no plateau found)"),
        xlabel="Pilot orbital (sorted by entropy)",
        ylabel="Single-orbital entropy $s^{(1)}$")
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        x = np.arange(len(sorted_entropies))
        ax.bar(x, sorted_entropies, color=colors, width=0.7)
        if threshold is not None:
            ax.axhline(threshold, color="tab:red", linestyle="--", linewidth=1,
                       label=f"threshold = {threshold:.4f}")
        st.apply(ax, legend_default=threshold is not None)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)


# Below this fraction of the ensemble spectrum's own peak, the broadened
# curve is tail rather than band. A Gaussian summed over a few hundred
# pooled transitions stays visibly non-zero for several eV either side of
# the absorption it describes, and the grid below is deliberately built
# from the pooled data's full extent plus five sigma of padding -- which
# is the right domain to COMPUTE on (no contribution is truncated) and the
# wrong one to look at, since the padding alone can be wider than the band
# it surrounds. So the x-axis is trimmed to where the total curve is at
# least this tall. Applied to the plot only: the .dat export written
# alongside it keeps the full grid, because that file is the raw data
# rather than a view of it.
_ENSEMBLE_PLOT_INTENSITY_CUTOFF = 0.08


def render_wigner_ensemble_spectrum(
    pooled_energies_eV: list[float], pooled_oscillator_strengths: list[float], pooled_state_indices: list[int],
    fwhm_eV: float, out_path: str, out_data_path: str | None = None,
    style: PlotStyle = None,
) -> None:
    """Nuclear-ensemble (Wigner) absorption spectrum: every pooled
    (energy, oscillator_strength) transition across an entire
    wigner_ensemble's sub-jobs, Gaussian-broadened and summed into one
    total spectrum, with a dotted per-excited-state-index overlay (S1,
    S2, ...) grouped by literal state index across the ensemble -- NOT by
    adiabatic/diabatic character, which this app has no way to track
    across independently-run sub-jobs at different geometries; states can
    genuinely reorder between samples, an inherent limitation of this
    representation, not a defect introduced here.

    Deliberately an eV x-axis throughout (unlike render_uvvis_plot's nm
    conversion for a single job) -- matches the conventional nuclear-
    ensemble-spectrum display convention this feature is modeled on.

    Total and every per-state overlay share ONE grid (built from the
    pooled data's own min/max, not any single sub-job's) and are
    normalized by the SAME divisor -- the total spectrum's own peak, not
    each series' own peak independently, which would misrepresent each
    state's real relative contribution to the total.

    The plotted x-range is trimmed to where the total curve rises above
    _ENSEMBLE_PLOT_INTENSITY_CUTOFF of its own peak, so the broadened
    band fills the axis instead of sharing it with several eV of tail.

    If out_data_path is given, also writes the same normalized
    (energy_eV, total, per-state...) columns as a whitespace-delimited
    text file, mirroring the source workflow's own spectrum.dat export.
    That export is deliberately NOT trimmed: it is the raw curve, and a
    user post-processing it should get everything the ensemble produced."""
    if not pooled_energies_eV:
        raise ValueError("No pooled transitions to plot")
    sigma = fwhm_eV / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    energies = np.asarray(pooled_energies_eV, dtype=float)
    lo = max(0.1, float(energies.min()) - 5 * sigma)
    hi = float(energies.max()) + 5 * sigma
    grid_eV = np.linspace(lo, hi, 2000)

    total = np.zeros_like(grid_eV)
    by_state: dict[int, np.ndarray] = {}
    for e, f, state_idx in zip(pooled_energies_eV, pooled_oscillator_strengths, pooled_state_indices):
        contribution = f * np.exp(-0.5 * ((grid_eV - e) / sigma) ** 2)
        total += contribution
        by_state.setdefault(state_idx, np.zeros_like(grid_eV))
        by_state[state_idx] += contribution

    divisor = float(total.max())
    if divisor <= 0:
        raise ValueError("Every pooled oscillator strength is zero -- nothing to plot")
    total_norm = total / divisor
    by_state_norm = {state_idx: series / divisor for state_idx, series in by_state.items()}

    st = (style or PlotStyle()).with_defaults(
        title=f"Nuclear-ensemble absorption spectrum (FWHM = {fwhm_eV:.2f} eV)",
        xlabel="Energy (eV)",
        ylabel="Normalized intensity (arb. units)",
    )
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        colors = plt.cm.nipy_spectral(np.linspace(0.1, 0.9, max(len(by_state_norm), 1)))
        for i, state_idx in enumerate(sorted(by_state_norm)):
            ax.plot(
                grid_eV, by_state_norm[state_idx], color=colors[i % len(colors)], linestyle="dotted",
                linewidth=1.2, alpha=0.9, label=f"S{state_idx} contribution",
            )
        ax.plot(grid_eV, total_norm, color="black", linewidth=st.lw(2.0), label=f"Total ({len(pooled_energies_eV)} transitions)")
        if st.ylim is None:
            ax.set_ylim(bottom=0, top=1.1)
        # Trim to the band, not the tails -- see _ENSEMBLE_PLOT_INTENSITY_CUTOFF.
        # Padded by a twentieth of the retained width so the curve meets the axis
        # rather than being clipped flush against it, and skipped entirely if the
        # cutoff retains nothing wider than a single grid point (a lone very
        # narrow spike), where a hard zoom would be less readable than the full
        # range it replaces.
        above_cutoff = np.flatnonzero(total_norm >= _ENSEMBLE_PLOT_INTENSITY_CUTOFF)
        if above_cutoff.size > 1 and st.xlim is None:
            lo_eV, hi_eV = grid_eV[above_cutoff[0]], grid_eV[above_cutoff[-1]]
            pad = (hi_eV - lo_eV) / 20.0
            ax.set_xlim(lo_eV - pad, hi_eV + pad)
        st.apply(ax, legend_default=True)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)

    if out_data_path:
        sorted_states = sorted(by_state_norm)
        header = "Energy(eV) Total_Intensity " + " ".join(f"State_{i}" for i in sorted_states)
        columns = [grid_eV, total_norm] + [by_state_norm[i] for i in sorted_states]
        export_data = np.column_stack(columns)
        np.savetxt(out_data_path, export_data, fmt="%.6f", header=header)


def render_uvvis_plot(
    energies_eV: list[float], oscillator_strengths: list[float], fwhm_eV: float, out_path: str,
    style: PlotStyle = None,
) -> None:
    """oscillator_strengths must already be all-numeric (no None entries)
    -- callers (see plot_excited_state_spectrum in tools.py) are
    responsible for refusing to plot when intensities aren't available at
    all, rather than silently treating missing values as zero here."""
    grid_eV, spectrum = _broadened_spectrum(energies_eV, oscillator_strengths, fwhm_eV)
    grid_nm = _EV_TO_NM / grid_eV
    order = np.argsort(grid_nm)

    st = (style or PlotStyle()).with_defaults(
        title=f"UV/Vis absorption spectrum (FWHM = {fwhm_eV:.2f} eV)",
        xlabel="Wavelength (nm)",
        ylabel="Oscillator strength (Gaussian-broadened, arb. units)",
    )
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        ax.plot(grid_nm[order], spectrum[order], color=st.accent("tab:blue"),
                linewidth=st.lw(1.5), linestyle=st.line_style,
                marker=st.marker, markersize=st.ms(3.0))
        stick_nm = [_EV_TO_NM / e for e in energies_eV]
        ax.vlines(stick_nm, 0, oscillator_strengths, color="tab:gray", alpha=0.6, linewidth=1)
        st.apply(ax)
        if st.ylim is None:
            ax.set_ylim(bottom=0)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi)
        plt.close(fig)
