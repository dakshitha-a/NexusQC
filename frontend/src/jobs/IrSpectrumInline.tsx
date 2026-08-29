// Client-side Gaussian broadening of a completed frequency job's own
// frequencies_cm-1/ir_intensities_km_mol -- same "compute retroactively in
// the browser, no backend change needed for already-completed jobs"
// reasoning as UvVisSpectrumInline.tsx; the explicit "Save plot" PNG tool
// (IrSpectrumPanel, backed by render_ir_spectrum_plot) is unaffected and
// still available as a job artifact.
import { MiniLineChart } from "./MiniLineChart";
import { broadenedSpectrum as broaden } from "./broadening";

const FWHM_CM1 = 20; // matches plot_ir_spectrum's default
// Matches app/chemistry/spectrum.py's _TRANS_ROT_FREQ_CUTOFF_CM1 -- drops
// the near-zero projected translational/rotational modes both engines
// still list, so they don't drag the plotted range down to include a dead
// zone before the first real vibration.
const TRANS_ROT_CUTOFF_CM1 = 10;

// The vibrational shape of the same implementation: cm-1 throughout, and a
// floor of 0 rather than 0.5, since a wavenumber axis has no division to
// protect. This was a second, independent copy of the formula until the
// shared module existed.
function broadenedSpectrum(freqsCm1: number[], intensities: number[], nPoints = 200) {
  return broaden(freqsCm1, intensities, FWHM_CM1, { nPoints, floor: 0 });
}

export function IrSpectrumInline({
  frequenciesCm1, intensities,
}: {
  frequenciesCm1: number[];
  intensities: number[];
}) {
  const pairs = frequenciesCm1
    .map((f, i) => [f, intensities[i]] as const)
    .filter(([f]) => Math.abs(f) >= TRANS_ROT_CUTOFF_CM1);
  if (pairs.length === 0) return null;
  const freqs = pairs.map(([f]) => f);
  const ir = pairs.map(([, i]) => i);
  const { grid, y } = broadenedSpectrum(freqs, ir);

  // Negate x so higher wavenumber renders on the left -- the conventional
  // IR-spectroscopy display direction (matches render_ir_spectrum_plot's
  // ax.set_xlim(hi, lo)). grid is already monotonic ascending by
  // construction, so negating it keeps the polyline monotonic (just
  // decreasing) without needing UvVisSpectrumInline's explicit re-sort,
  // which that component needs only because its eV->nm conversion is
  // non-linear.
  return (
    <MiniLineChart
      x={grid.map((f) => -f)}
      series={[{ label: "IR", y }]}
      sticks={freqs.map((f, i) => ({ x: -f, y: ir[i] }))}
      xLabel="Wavenumber (cm⁻¹)"
      yLabel={`Intensity (FWHM ${FWHM_CM1} cm⁻¹)`}
    />
  );
}
