// P8.3: live Gaussian broadening for a wigner_spectra master's pooled
// transitions. Fetches the pooled (energy, oscillator-strength) pairs ONCE
// (useWignerTransitionsQuery) and re-broadens entirely client-side on every
// slider move, reusing UvVisSpectrumInline's own broadenedSpectrum function
// parametrized on fwhmEv -- one broadening implementation, not a second one
// that could drift from app/chemistry/spectrum.py's server-side arithmetic.
// No network request fires on a slider move: the slider only feeds a
// useMemo over already-fetched data.
import { useMemo, useState } from "react";
import { useWignerTransitionsQuery } from "../lib/queries";
import { broadenedSpectrum, DEFAULT_FWHM_EV } from "./UvVisSpectrumInline";
import { MiniLineChart } from "./MiniLineChart";

const EV_TO_NM = 1239.841984;

export function WignerBroadeningPanel({ jobId, running }: { jobId: string; running: boolean }) {
  const query = useWignerTransitionsQuery(jobId, true, running);
  const [fwhm, setFwhm] = useState(DEFAULT_FWHM_EV);

  const pooled = query.data?.pooled;
  const diagnostics = query.data?.diagnostics;

  const chart = useMemo(() => {
    if (!pooled || pooled.energies_eV.length === 0) return null;
    const { grid, y } = broadenedSpectrum(pooled.energies_eV, pooled.oscillator_strengths, fwhm);
    const xNmGrid = grid.map((e) => EV_TO_NM / e);
    // grid is ascending in eV, i.e. descending in nm -- reverse so the
    // chart's x-axis reads left-to-right, same as UvVisSpectrumInline.
    const order = xNmGrid.map((_, i) => i).sort((a, b) => xNmGrid[a] - xNmGrid[b]);
    const sticks = pooled.energies_eV.map((e, i) => ({ x: EV_TO_NM / e, y: pooled.oscillator_strengths[i] }));
    return { x: order.map((i) => xNmGrid[i]), y: order.map((i) => y[i]), sticks };
  }, [pooled, fwhm]);

  if (query.isLoading) {
    return <div className="text-xs text-text-muted">Loading pooled transitions...</div>;
  }
  if (query.isError || !pooled) {
    return <div className="text-xs text-status-failed">Could not load the ensemble's pooled transitions.</div>;
  }
  if (!chart) {
    return (
      <div className="text-xs text-text-muted">
        No transitions with usable intensity to broaden yet
        {diagnostics && diagnostics.n_completed > 0 && diagnostics.n_no_intensity === diagnostics.n_completed
          ? " -- this method/engine combination doesn't report oscillator strengths."
          : "."}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2" data-testid="wigner-broadening-panel">
      <MiniLineChart
        x={chart.x} series={[{ label: "Ensemble", y: chart.y }]} sticks={chart.sticks}
        xLabel="Wavelength (nm)" yLabel={`f (FWHM ${fwhm.toFixed(2)} eV)`}
      />
      <label className="flex items-center gap-2 text-[10.5px] text-text-muted">
        Broadening (FWHM, eV)
        <input
          type="range"
          min={0.05}
          max={1.5}
          step={0.01}
          value={fwhm}
          onChange={(e) => setFwhm(Number(e.target.value))}
          className="qc-range flex-1"
          aria-label="Broadening FWHM in eV"
          data-testid="wigner-fwhm-slider"
        />
        <span className="w-10 font-mono text-text" data-testid="wigner-fwhm-value">{fwhm.toFixed(2)}</span>
      </label>
      {diagnostics && (
        <div className="text-[11px] text-text-muted">
          {diagnostics.n_transitions_pooled} transitions pooled from {diagnostics.n_completed} of{" "}
          {diagnostics.n_sub_jobs} samples
          {diagnostics.n_no_intensity > 0 && `, ${diagnostics.n_no_intensity} with no intensity data`}
          {diagnostics.n_failed_or_pending > 0 && `, ${diagnostics.n_failed_or_pending} still running or failed`}.
        </div>
      )}
    </div>
  );
}
