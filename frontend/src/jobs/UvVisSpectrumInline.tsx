// Client-side Gaussian broadening of a completed job's own
// excitation_energies_eV/oscillator_strengths -- deliberately NOT computed
// server-side at parse time (unlike the plan's original sketch): the exact
// same arithmetic as app/chemistry/spectrum.py's _broadened_spectrum works
// retroactively on every already-completed job with zero backend change,
// where a parse-time field would only ever populate for jobs run after that
// change shipped. The explicit "Save plot" PNG tool (UvVisPanel, backed by
// render_uvvis_plot) is unaffected and still available as a job artifact.
import { MiniLineChart } from "./MiniLineChart";

const EV_TO_NM = 1239.841984;
export const DEFAULT_FWHM_EV = 0.4; // matches plot_excited_state_spectrum's default

// Exported (Phase 8 P8.3) so WignerBroadeningPanel's live slider re-broadens
// pooled ensemble transitions with the SAME arithmetic, parametrized on
// fwhmEv instead of the fixed default -- one broadening implementation,
// not two that could drift apart.
//
// `range` overrides the grid's own extent, for a caller showing a zoomed
// window (WignerBroadeningPanel's energy slider). It changes only where
// the grid's nPoints land, never a value: every transition still
// contributes its full Gaussian to every point, so a point inside the
// window has the same y whether or not the window is applied -- the zoom
// gains resolution instead of spending most of its points off-screen.
export function broadenedSpectrum(
  energiesEv: number[], strengths: number[], fwhmEv = DEFAULT_FWHM_EV, nPoints = 200,
  range?: [number, number],
) {
  const sigma = fwhmEv / (2 * Math.sqrt(2 * Math.log(2)));
  const lo = range ? range[0] : Math.max(0.5, Math.min(...energiesEv) - 5 * sigma);
  const hi = range ? range[1] : Math.max(...energiesEv) + 5 * sigma;
  const step = (hi - lo) / (nPoints - 1);
  const grid = Array.from({ length: nPoints }, (_, i) => lo + i * step);
  const y = grid.map((e) =>
    energiesEv.reduce((acc, e0, i) => acc + strengths[i] * Math.exp(-0.5 * ((e - e0) / sigma) ** 2), 0),
  );
  return { grid, y };
}

export function UvVisSpectrumInline({ energiesEv, strengths }: { energiesEv: number[]; strengths: number[] }) {
  const { grid, y } = broadenedSpectrum(energiesEv, strengths, DEFAULT_FWHM_EV);
  const xNm = grid.map((e) => EV_TO_NM / e);
  const sticks = energiesEv.map((e, i) => ({ x: EV_TO_NM / e, y: strengths[i] }));
  // grid is ascending in eV, i.e. descending in nm -- reverse so the chart's x-axis reads left-to-right.
  const order = xNm.map((_, i) => i).sort((a, b) => xNm[a] - xNm[b]);
  return (
    <MiniLineChart
      x={order.map((i) => xNm[i])}
      series={[{ label: "Absorption", y: order.map((i) => y[i]) }]}
      sticks={sticks}
      xLabel="Wavelength (nm)"
      yLabel={`f (FWHM ${DEFAULT_FWHM_EV} eV)`}
    />
  );
}
