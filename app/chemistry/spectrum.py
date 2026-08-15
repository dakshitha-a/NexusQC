"""Gaussian-broadened UV/Vis absorption spectrum rendering from discrete
excitation energies + oscillator strengths, as reported in a completed
tddft/eom_ccsd/casscf(want_oscillator_strengths=True) job summary."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless -- this runs inside a server/agent process, never a display
import matplotlib.pyplot as plt
import numpy as np

_EV_TO_NM = 1239.841984


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
) -> None:
    """Shared publication-style (white background, real ticks, legend when
    there's more than one series) matplotlib line plot -- one line per
    dict entry in y_series, `None` entries plotted as gaps (a failed
    pes_scan image, see render_pes_plot) rather than interpolated across
    or silently dropped. Used for pes_scan's energy-vs-coordinate plot and
    reused for the on-demand PNG-download rendering of the existing
    frontend-only optimization-energy/UV-Vis-inline charts (see
    server/routes/jobs.py's render_plot route)."""
    fig, ax = plt.subplots(figsize=(6.5, 4))
    for label, y in y_series.items():
        y_masked = [v if v is not None else np.nan for v in y]
        ax.plot(x, y_masked, marker="o", markersize=3, linewidth=1.5, label=label)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if len(y_series) > 1:
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)


_HARTREE_TO_KCAL_MOL = 627.5094740631


def render_pes_plot(
    coordinate_values: list[float], state_energies_hartree: dict[str, list[float | None]],
    coordinate_label: str, out_path: str,
) -> None:
    """PES scan plot -- one line per electronic state, in relative energy
    (kcal/mol, referenced to the lowest known energy across every state/
    image so multiple states share one consistent zero), image indices
    with no successful energy plotted as a gap (see JobResult in
    app/chemistry/jobs/scan_orchestrator.py's "completed with gaps"
    handling of a partially-failed scan)."""
    known = [v for series in state_energies_hartree.values() for v in series if v is not None]
    if not known:
        raise ValueError("No successful images to plot -- every sub-job in this scan failed")
    zero = min(known)
    relative = {
        label: [(v - zero) * _HARTREE_TO_KCAL_MOL if v is not None else None for v in series]
        for label, series in state_energies_hartree.items()
    }
    render_line_plot(
        coordinate_values, relative, coordinate_label, "Relative energy (kcal/mol)",
        "Potential energy scan", out_path,
    )


_HARTREE_TO_EV = 27.211386245988


def render_neb_plot(path_rows: list[dict], out_path: str) -> None:
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

    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(xs, ys, marker="o", markersize=4, linewidth=1.5, color="#3b6fd6", label="Path")
    if ts_rows:
        ci_row = next((r for r in numbered if r.get("marker") == "CI"), None)
        ts_x = int(ci_row["image"]) if ci_row else xs[len(xs) // 2]
        ts_y = (ts_rows[0]["energy_hartree"] - zero) * _HARTREE_TO_EV
        ax.scatter([ts_x], [ts_y], color="#d6483b", zorder=5, s=70, marker="^", label="TS (refined)")
    ax.set_xlabel("Image")
    ax.set_ylabel("Relative energy (eV)")
    ax.set_title("NEB-TS reaction path")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)


_TRANS_ROT_FREQ_CUTOFF_CM1 = 10.0


def render_ir_spectrum_plot(
    frequencies_cm1: list[float], ir_intensities_km_mol: list[float], fwhm_cm1: float, out_path: str,
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

    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(grid, spectrum, color="tab:blue", linewidth=1.5)
    ax.vlines(freqs, 0, ir, color="tab:gray", alpha=0.6, linewidth=1)
    ax.set_xlabel("Wavenumber (cm$^{-1}$)")
    ax.set_ylabel("IR intensity (Gaussian-broadened, km/mol)")
    ax.set_title(f"IR spectrum (FWHM = {fwhm_cm1:.0f} cm$^{{-1}}$)")
    ax.set_xlim(hi, lo)  # conventional IR-spectroscopy display: high wavenumber on the left
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def render_uvvis_plot(
    energies_eV: list[float], oscillator_strengths: list[float], fwhm_eV: float, out_path: str,
) -> None:
    """oscillator_strengths must already be all-numeric (no None entries)
    -- callers (see plot_excited_state_spectrum in tools.py) are
    responsible for refusing to plot when intensities aren't available at
    all, rather than silently treating missing values as zero here."""
    grid_eV, spectrum = _broadened_spectrum(energies_eV, oscillator_strengths, fwhm_eV)
    grid_nm = _EV_TO_NM / grid_eV
    order = np.argsort(grid_nm)

    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(grid_nm[order], spectrum[order], color="tab:blue", linewidth=1.5)
    stick_nm = [_EV_TO_NM / e for e in energies_eV]
    ax.vlines(stick_nm, 0, oscillator_strengths, color="tab:gray", alpha=0.6, linewidth=1)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Oscillator strength (Gaussian-broadened, arb. units)")
    ax.set_title(f"UV/Vis absorption spectrum (FWHM = {fwhm_eV:.2f} eV)")
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
