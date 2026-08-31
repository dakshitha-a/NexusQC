"""Charts built from data every job already reports, and which had no view.

Four shapes, all of them adapters onto marks `spectrum.py` already draws: an
MO diagram is `levels` with two colours, a convergence trace is a line, a
sampling check is a histogram. They are functions here rather than `custom`
plot specs because each needs a little domain arithmetic -- which orbital is
the HOMO, what the energies are measured from, which unit the answer is read
in -- that a declarative spec cannot express and a user should not have to
supply by hand.

They live in their own module rather than in `spectrum.py` because that file
is about spectra and broadening, and was already carrying four renderers that
are not spectra. Everything shared stays shared: the same `PlotStyle`
vocabulary, the same `rc_context`-per-figure rule, the same white background
and the same "an unstyled render is what it always was" contract.

Why each exists, in the order they were added:

- **MO energies** are on 156 of the 162 jobs in the development data
  directory and were displayed nowhere. Every excited-state question starts
  with the frontier orbitals.
- **The optimization trace** was drawn client-side as a sparkline in the job
  drawer, with no file behind it, so it could not be downloaded, attached to a
  prompt, restyled or kept. `app/plots/intrinsic.py` used to name it as the
  one genuinely client-side chart; that stopped being a reason once the NEB
  and PES plots became saved records for the same reason.
- **The excited-state map** answers what a broadened spectrum cannot: a band
  does not say which state it came from or which orbitals moved.
- **Sampling diagnostics** are the standard check that a Wigner ensemble is
  sane before anyone believes its spectrum, from numbers already pooled onto
  the master job.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless, exactly as spectrum.py -- never a display
import matplotlib.pyplot as plt  # noqa: E402
from dataclasses import replace  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from app.chemistry.plot_style import PlotStyle  # noqa: E402
from app.chemistry.units import HARTREE_TO_EV  # noqa: E402

# The same red spectrum.py marks an equilibrium reference with, imported
# rather than restated so a dashed red line cannot come to mean two slightly
# different colours on two charts in the same app.
from app.chemistry.spectrum import _EQUILIBRIUM_RED as _REFERENCE_RED  # noqa: E402

# Occupied, virtual, and the pair either side of the gap. Deliberately not the
# categorical palette: these are two states of one thing, not two series.
_MO_OCCUPIED = "#0072B2"
_MO_VIRTUAL = "#B0B7BE"
_MO_FRONTIER = "#D55E00"


def _frontier_is_placeholder(occupied: list) -> bool:
    """Whether the highest occupied orbital's energy is a filler zero.

    Checked on the data rather than on a `orbital_table_kind` flag the caller
    passes, so the renderer is safe whoever calls it. The signature of the
    natural-orbital case is unmistakable: the frontier orbital sits at exactly
    0.0 while the core orbitals of the same table are hundreds of eV below it.
    A genuine canonical HOMO is never exactly zero to the bit.
    """
    if not occupied:
        return False
    if occupied[-1].get("energy_eV") != 0.0:
        return False
    return any((r.get("energy_eV") or 0.0) < -1.0 for r in occupied)


def render_mo_diagram(
    orbital_table: list[dict], out_path: str, window: int = 8, style: PlotStyle = None,
) -> None:
    """Molecular-orbital energy levels, occupied below the gap and virtual
    above it, with the HOMO and LUMO picked out and the gap annotated.

    `orbital_table` is what every job writing a molden already carries (see
    each runner's `_add_orbital_table`): rows of {index, energy_eV,
    occupancy}. A real table runs to a hundred and thirty rows and nobody is
    asking about orbital 3 of 132, so `window` caps how many are drawn either
    side of the gap.

    Occupancy, not index, decides what counts as occupied. A state-averaged
    CASSCF active orbital has a fractional occupancy, and reading anything
    above zero as filled is what makes this correct for a multireference job
    as well as a closed-shell one.
    """
    rows = [r for r in orbital_table if r.get("energy_eV") is not None]
    if not rows:
        raise ValueError("No orbital energies to draw a level diagram from")
    rows.sort(key=lambda r: r["energy_eV"])
    occupied = [r for r in rows if (r.get("occupancy") or 0) > 0.0]
    virtual = [r for r in rows if (r.get("occupancy") or 0) <= 0.0]
    homo = occupied[-1] if occupied else None
    lumo = virtual[0] if virtual else None

    # A natural-orbital table carries occupancies and NO eigenvalues: every
    # active orbital comes back with energy_eV exactly 0.0, which is a
    # placeholder and not an energy. Drawing it puts nine levels on top of
    # each other at zero, calls the top one the HOMO, and annotates a gap
    # measured from a number nobody computed. Refused rather than drawn,
    # because a fabricated quantity on an axis is worse than no chart -- the
    # summary that carries such a table says so itself, in
    # `frontier_energy_unavailable`.
    if _frontier_is_placeholder(occupied):
        raise ValueError(
            "This job's orbital table is natural orbitals, which carry occupancies but no orbital "
            "energies -- every active orbital is recorded at exactly 0.0 eV as a placeholder. An "
            "energy-level diagram drawn from it would show a stack of levels at zero and a "
            "HOMO-LUMO gap measured from a number that was never computed. The occupancies and "
            "indices ARE real; the energies are not."
        )

    shown = occupied[-window:] + virtual[:window]
    if not shown:
        raise ValueError("No orbitals left to draw after windowing")

    st = (style or PlotStyle()).with_defaults(
        title="Molecular orbital energies", xlabel="", ylabel="Orbital energy (eV)")
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        for row in shown:
            frontier = row is homo or row is lumo
            filled = (row.get("occupancy") or 0) > 0.0
            color = _MO_FRONTIER if frontier else (_MO_OCCUPIED if filled else _MO_VIRTUAL)
            ax.hlines(row["energy_eV"], -0.35, 0.35, color=color,
                      linewidth=st.lw(3.0 if frontier else 2.0))
            # The index sits beside its own level rather than on an axis: the
            # levels are not evenly spaced, so a tick per orbital would either
            # overlap or lie about the spacing.
            ax.annotate(str(row["index"]), xy=(0.38, row["energy_eV"]), va="center", ha="left",
                        fontsize=st.size("tick_size") * 0.8, color="#606060")
        if homo is not None and lumo is not None:
            gap = lumo["energy_eV"] - homo["energy_eV"]
            mid = (lumo["energy_eV"] + homo["energy_eV"]) / 2.0
            ax.annotate("", xy=(-0.5, lumo["energy_eV"]), xytext=(-0.5, homo["energy_eV"]),
                        arrowprops=dict(arrowstyle="<->", color=_MO_FRONTIER, linewidth=1.2))
            ax.annotate(f"gap {gap:.2f} eV", xy=(-0.55, mid), ha="right", va="center",
                        color=_MO_FRONTIER, fontsize=st.size("tick_size"))
        ax.set_xlim(-1.35, 0.9)
        ax.set_xticks([])
        st.apply(ax)
        if st.legend is not False:
            # Proxy handles: hlines returns a LineCollection per call, so
            # labelling them directly puts one legend entry per drawn level.
            handles = [Line2D([0], [0], color=_MO_OCCUPIED, linewidth=2.0, label="Occupied"),
                       Line2D([0], [0], color=_MO_VIRTUAL, linewidth=2.0, label="Virtual"),
                       Line2D([0], [0], color=_MO_FRONTIER, linewidth=3.0, label="HOMO / LUMO")]
            if isinstance(st.legend, str):
                ax.legend(handles=handles, loc=st.legend)
            else:
                # Below the axes, in one row. Every in-axes corner is
                # occupied here: the levels sit centre-right, their index
                # labels run down the right edge, and the gap arrow and its
                # label take the left. A "lower right" default sat squarely
                # on the HOMO of a real 132-orbital job.
                ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.04),
                          ncol=3, frameon=False)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)


def render_optimization_trace(
    energies_hartree: list, out_path: str, converged=None, style: PlotStyle = None,
) -> None:
    """A geometry optimization's energy against step, relative to the energy
    it finished at.

    Absolute energies along an optimization differ in the sixth decimal, and a
    plot of them is a flat line. The legible quantity is how far each step
    still was from where it ended up. That is also why a log axis is the
    default when every point is positive: the last few steps are the ones
    people squint at, and they are orders of magnitude smaller than the first.

    In eV, like every other relative energy this app reports. kcal/mol is the
    unit the wider literature quotes a barrier in and it is NOT the convention
    here -- `units.RELATIVE_UNITS` is hartree and eV on purpose, and the PES
    scan, the NEB path and every excitation are already in eV. This chart was
    written in kcal/mol first, which is exactly the easy mistake: the unit
    reads as natural for a difference.
    """
    values = [e for e in energies_hartree if e is not None]
    if len(values) < 2:
        raise ValueError("An optimization trace needs at least two steps")
    final = values[-1]
    relative = [(e - final) * HARTREE_TO_EV for e in values]
    # Every step before the last strictly above the final energy. A step that
    # went below and came back is a real thing an optimizer does, and it has
    # no place on a log axis, so that run gets the linear view.
    use_log = len(relative) > 2 and all(r > 0 for r in relative[:-1])

    title = "Geometry optimization"
    if converged is not None:
        title += ", converged" if converged else ", NOT converged"
    st = (style or PlotStyle()).with_defaults(
        title=title, xlabel="Optimization step", ylabel="Energy above final (eV)")
    if not st.log_y and use_log:
        st = replace(st, log_y=True)
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        steps = list(range(1, len(relative) + 1))
        # The final step IS the reference, so its value is exactly zero, and
        # zero cannot go on a log axis. It is dropped from the log view rather
        # than the axis being abandoned -- and said so, because a reader
        # counting points would otherwise find one missing with no reason.
        xs, ys = (steps[:-1], relative[:-1]) if st.log_y else (steps, relative)
        ax.plot(xs, ys, marker=st.marker or "o", markersize=st.ms(4.0),
                linewidth=st.lw(1.5), linestyle=st.line_style,
                color=st.accent("#3b6fd6"), label="Energy above final")
        if st.log_y:
            ax.annotate(f"step {len(relative)} is the zero, off a log axis",
                        xy=(0.98, 0.95), xycoords="axes fraction", ha="right", va="top",
                        fontsize=st.size("tick_size") * 0.85, color="#606060")
        st.apply(ax)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)


def render_excited_state_map(
    energies_eV: list, oscillator_strengths: list, labels: list, out_path: str,
    style: PlotStyle = None,
) -> None:
    """One bar per excited state, at its excitation energy, as tall as its
    oscillator strength, annotated with the orbital pair that dominates it.

    The view a broadened spectrum cannot give. The curve shows a band, and a
    band does not say which state it came from or which orbitals moved.
    `labels` are the `dominant_transitions` strings the runners already parse
    ("28->30 (0.73)"); a missing one costs the annotation, never the bar.
    """
    if not energies_eV:
        raise ValueError("No excited states to draw")
    osc = [0.0 if f is None else float(f) for f in oscillator_strengths]
    st = (style or PlotStyle()).with_defaults(
        title="Excited states", xlabel="Excitation energy (eV)", ylabel="Oscillator strength")
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        span = (max(energies_eV) - min(energies_eV)) or 1.0
        ax.bar(energies_eV, osc, width=span * 0.012, color=st.accent("#0072B2"))
        for i, (e, f) in enumerate(zip(energies_eV, osc)):
            text = f"S{i + 1}"
            if i < len(labels) and labels[i]:
                text += "\n" + str(labels[i])
            ax.annotate(text, xy=(e, f), xytext=(0, 5), textcoords="offset points",
                        ha="center", va="bottom",
                        fontsize=st.size("tick_size") * 0.8, color="#404040")
        tallest = max(osc, default=0.0)
        if st.ylim is None and tallest > 0:
            # Headroom for the annotations, which sit above the bars and which
            # matplotlib does not measure when it autoscales.
            ax.set_ylim(0, tallest * 1.35)
        elif st.ylim is None:
            # Every state dark. An autoscaled axis collapses onto zero, so say
            # what happened rather than drawing an empty box.
            ax.set_ylim(0, 1)
            ax.annotate("every transition has zero oscillator strength",
                        xy=(0.5, 0.5), xycoords="axes fraction", ha="center",
                        color="#606060", fontsize=st.size("tick_size"))
        st.apply(ax)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)


def render_thermochemistry(
    electronic_energy_hartree: float, zero_point_energy_hartree: float,
    enthalpy_hartree: float, gibbs_free_energy_hartree: float, out_path: str,
    temperature_K=None, style: PlotStyle = None,
) -> None:
    """What separates a bare electronic energy from a free energy, as a
    waterfall: zero-point, then the thermal correction, then the entropy term.

    Drawn as increments from the electronic energy rather than four absolute
    values, because the absolutes are around -414 hartree and differ from each
    other in the second decimal -- four bars of equal height. The increments
    are what the chart is for, and they are what a reader is deciding between
    when they ask whether to quote E, H or G.

    In eV, like every relative energy this app reports.

    Each contribution is derived rather than taken on trust, so the bars
    cannot disagree with the numbers they came from: the thermal term is
    H - (E + ZPE) and the entropy term is G - H. That also means -TS is read
    off the two energies rather than recomputed from S and T, which would
    silently disagree with them whenever the engine used a different standard
    state than this code assumed.
    """
    zpe = (zero_point_energy_hartree or 0.0) * HARTREE_TO_EV
    total_h = (enthalpy_hartree - electronic_energy_hartree) * HARTREE_TO_EV
    total_g = (gibbs_free_energy_hartree - electronic_energy_hartree) * HARTREE_TO_EV
    thermal = total_h - zpe
    entropy_term = total_g - total_h

    # (label, increment, the cumulative height it starts from)
    steps = [
        ("Zero-point", zpe, 0.0),
        ("Thermal", thermal, zpe),
        ("-T$\\Delta$S", entropy_term, total_h),
    ]
    subtitle = f"{temperature_K:g} K" if temperature_K else ""
    st = (style or PlotStyle()).with_defaults(
        title="Electronic energy to Gibbs free energy" + (f" ({subtitle})" if subtitle else ""),
        xlabel="", ylabel="Energy relative to the electronic energy (eV)")
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        # Two flat markers for the endpoints, three floating bars between
        # them. The endpoints are levels rather than bars because they are
        # states, and the things between them are changes.
        ax.hlines(0.0, -0.45, 0.45, color=_MO_FRONTIER, linewidth=st.lw(3.0))
        ax.hlines(total_g, len(steps) + 0.55, len(steps) + 1.45,
                  color=_MO_FRONTIER, linewidth=st.lw(3.0))
        for i, (label, delta, base) in enumerate(steps, start=1):
            # Blue up, orange down, so the sign is legible before the number
            # is read. The entropy term is the one that normally goes down.
            color = "#0072B2" if delta >= 0 else "#D55E00"
            ax.bar(i, delta, bottom=base, width=0.6, color=color)
            top = base + delta
            # A rising bar is labelled above its top and a falling one below
            # its foot. Labelling both at the higher end put the thermal
            # term's caption and the entropy term's on almost the same line,
            # where they overlapped each other and the title.
            if delta >= 0:
                anchor, offset, va = max(base, top), 5, "bottom"
            else:
                anchor, offset, va = min(base, top), -5, "top"
            ax.annotate(f"{delta:+.3f}", xy=(i, anchor), xytext=(0, offset),
                        textcoords="offset points", ha="center", va=va,
                        fontsize=st.size("tick_size") * 0.85, color="#404040")
            # A dotted guide from each bar's top to the next bar's foot, so
            # the eye follows the running total rather than reading three
            # unconnected bars.
            if i < len(steps):
                ax.plot([i + 0.3, i + 0.7], [top, top], linestyle=":",
                        color="#909090", linewidth=1.0)
        ax.plot([len(steps) + 0.3, len(steps) + 0.55], [total_g, total_g],
                linestyle=":", color="#909090", linewidth=1.0)

        ax.set_xticks(range(len(steps) + 2))
        ax.set_xticklabels(["E$_{elec}$"] + [s[0] for s in steps] + ["G"])
        ax.axhline(0.0, color="#c0c0c0", linewidth=0.8, zorder=0)
        if st.ylim is None:
            # Room for the captions at both ends. matplotlib does not measure
            # annotations when it autoscales, so without this the topmost
            # caption runs into the title -- which is what the first render
            # of this chart did.
            levels = [0.0, zpe, total_h, total_g]
            lo, hi = min(levels), max(levels)
            pad = (hi - lo or 1.0) * 0.18
            ax.set_ylim(lo - pad, hi + pad)
        st.apply(ax)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)


def render_sampling_diagnostics(
    harmonic_potential_hartree: list, out_path: str, temperature_K=None,
    style: PlotStyle = None,
) -> None:
    """How a Wigner ensemble's sampled geometries are distributed in harmonic
    potential energy above the equilibrium.

    The standard check that an ensemble is sane before anyone believes the
    spectrum pooled from it: samples should cluster low with a tail, not pile
    up against the edge of the sampled range. The numbers are already on the
    master job as `per_sample_harmonic_potential_hartree` and had no view.

    In eV, like every other relative energy this app reports, and beside a
    spectrum whose own axis is in eV -- which is the reading this chart is
    held up against.
    """
    values = [v for v in harmonic_potential_hartree if v is not None]
    if len(values) < 2:
        raise ValueError("A sampling diagnostic needs at least two samples")
    energies_eV = [v * HARTREE_TO_EV for v in values]
    mean = sum(energies_eV) / len(energies_eV)
    subtitle = f"{len(energies_eV)} samples"
    if temperature_K:
        subtitle += f", {temperature_K:g} K"

    st = (style or PlotStyle()).with_defaults(
        title=f"Wigner sampling ({subtitle})",
        xlabel="Harmonic potential above equilibrium (eV)", ylabel="Samples")
    with plt.rc_context(st.rc()):
        fig, ax = plt.subplots(figsize=st.figsize)
        ax.hist(energies_eV, bins="auto", color=st.accent("#3b6fd6"), edgecolor="white")
        ax.axvline(mean, color=_REFERENCE_RED, linestyle="--", linewidth=1.6, zorder=3)
        # Positioned in axes fraction on y and rotated, the same treatment the
        # equilibrium marker on a geometry distribution gets, so the two read
        # as the same kind of annotation.
        ax.annotate(f"mean {mean:.3f} eV",
                    xy=(mean, 0.98), xycoords=ax.get_xaxis_transform(),
                    xytext=(5, 0), textcoords="offset points",
                    color=_REFERENCE_RED, rotation=90, ha="left", va="top",
                    fontsize=st.size("tick_size") * 0.85,
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                              edgecolor="none", alpha=0.85))
        st.apply(ax)
        fig.tight_layout()
        fig.savefig(out_path, dpi=st.dpi, facecolor="white")
        plt.close(fig)
