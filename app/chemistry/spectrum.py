"""Gaussian-broadened UV/Vis absorption spectrum rendering from discrete
excitation energies + oscillator strengths, as reported in a completed
tddft/eom_ccsd/casscf(want_oscillator_strengths=True) job summary."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless -- this runs inside a Streamlit/agent process, never a display
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
