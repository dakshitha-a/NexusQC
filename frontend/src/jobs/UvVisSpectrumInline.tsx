// Client-side Gaussian broadening of a completed job's own
// excitation_energies_eV/oscillator_strengths -- deliberately NOT computed
// server-side at parse time (unlike the plan's original sketch): the exact
// same arithmetic as app/chemistry/spectrum.py's _broadened_spectrum works
// retroactively on every already-completed job with zero backend change,
// where a parse-time field would only ever populate for jobs run after that
// change shipped. The explicit "Save plot" PNG tool (UvVisPanel, backed by
// render_uvvis_plot) is unaffected and still available as a job artifact.
import { MiniLineChart } from "./MiniLineChart";
import { broadenedSpectrum as broaden } from "./broadening";

const EV_TO_NM = 1239.841984;
// Matches DEFAULT_UVVIS_FWHM_EV in app/chemistry/registry2/params.py, so the
// in-browser preview opens on the same curve the server-rendered figure will
// produce. Was 0.4, the textbook convention; lowered to 0.2 on 2026-08-24 so a
// spectrum keeps the structure it resolved instead of smearing neighbouring
// transitions into one band.
export const DEFAULT_FWHM_EV = 0.2;

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
// The electronic-spectrum shape of the shared implementation: eV throughout,
// and a 0.5 eV floor because a wavelength axis divides by energy. Kept as a
// named export because WignerBroadeningPanel imports it by this name.
export function broadenedSpectrum(
  energiesEv: number[], strengths: number[], fwhmEv = DEFAULT_FWHM_EV, nPoints = 200,
  range?: [number, number],
) {
  return broaden(energiesEv, strengths, fwhmEv, { nPoints, floor: 0.5, range });
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
