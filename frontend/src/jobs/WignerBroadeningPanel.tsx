// P8.3: live Gaussian broadening for a wigner_spectra master's pooled
// transitions. Fetches the pooled (energy, oscillator-strength) pairs ONCE
// (useWignerTransitionsQuery) and re-broadens entirely client-side on every
// slider move, reusing UvVisSpectrumInline's own broadenedSpectrum function
// parametrized on fwhmEv -- one broadening implementation, not a second one
// that could drift from app/chemistry/spectrum.py's server-side arithmetic.
// No network request fires on a slider move: the slider only feeds a
// useMemo over already-fetched data.
//
// The axis is eV, not the nm UvVisSpectrumInline uses for a single job's
// UV/Vis spectrum. Nuclear-ensemble spectra are read in eV by convention,
// and render_wigner_ensemble_spectrum -- the server-rendered final plot
// this panel previews -- has always plotted eV, so the preview and the
// finished figure now put the same feature at the same place on the axis.
//
// The final plot answers the tail problem by trimming its x-range at a
// fixed fraction of the peak (_ENSEMBLE_PLOT_INTENSITY_CUTOFF); the
// preview answers it with the energy-window slider below instead, which
// is the better tool while a user is still hunting for the region worth
// looking at. Deliberately no fixed cutoff here: a window the user chose
// should show whatever is inside it, including a weak shoulder that a
// cutoff would erase.
import { useMemo, useState } from "react";
import { useWignerTransitionsQuery } from "../lib/queries";
import { broadenedSpectrum } from "./UvVisSpectrumInline";
import { MiniLineChart } from "./MiniLineChart";

/** Where the broadening slider starts -- kept equal to
 * DEFAULT_ENSEMBLE_FWHM_EV in app/chemistry/registry2/params.py, so this
 * preview opens showing the same curve the server-rendered final figure
 * will produce. Kept as its own constant rather than reusing
 * UvVisSpectrumInline's DEFAULT_FWHM_EV even though the two now hold the
 * same 0.2: they are two knobs, for two reasons. An ensemble already
 * carries its band width in the spread of its samples, while a single
 * geometry's handful of stick transitions has only the broadening to turn
 * them into bands, so a later change to one should not silently move the
 * other. The broadening arithmetic is still shared with that module. */
const DEFAULT_ENSEMBLE_FWHM_EV = 0.2;

/** Slack added either side of the pooled transitions' own energy extent to
 * get the window slider's travel, so the broadened flanks of the outermost
 * transitions stay reachable rather than sitting just off the end. */
const WINDOW_MARGIN_EV = 0.5;
const WINDOW_STEP_EV = 0.05;
/** Never let the two thumbs close onto each other. A zero-width window
 * still produces a grid (it is rebuilt over whatever the window is), but
 * every point in it sits at the same energy, which draws as a degenerate
 * vertical smear and leaves no way back except the reset link. */
const MIN_WINDOW_EV = 0.2;

export function WignerBroadeningPanel({ jobId, running }: { jobId: string; running: boolean }) {
  const query = useWignerTransitionsQuery(jobId, true, running);
  const [fwhm, setFwhm] = useState(DEFAULT_ENSEMBLE_FWHM_EV);
  // null until the user actually drags a thumb, and only then a concrete
  // pair. While the master is still running the query keeps polling and
  // fresh samples widen the energy extent underneath us; leaving this null
  // lets the view follow that growth, and once it is set, the clamp below
  // adjusts a stale selection to the new bounds instead of resetting it to
  // full range and throwing away the window the user picked.
  const [energyWindow, setEnergyWindow] = useState<[number, number] | null>(null);

  const pooled = query.data?.pooled;
  const diagnostics = query.data?.diagnostics;

  // The slider's travel comes from the transitions themselves, not from the
  // broadened grid -- the grid's extent is a function of fwhm (it pads by
  // 5 sigma), so deriving bounds from it would make the window jump every
  // time the broadening slider moved.
  const bounds = useMemo(() => {
    if (!pooled || pooled.energies_eV.length === 0) return null;
    const lo = Math.max(0, Math.min(...pooled.energies_eV) - WINDOW_MARGIN_EV);
    const hi = Math.max(...pooled.energies_eV) + WINDOW_MARGIN_EV;
    return { lo, hi: Math.max(hi, lo + MIN_WINDOW_EV) };
  }, [pooled]);

  const [winLo, winHi] = useMemo(() => {
    if (!bounds) return [0, 1];
    if (!energyWindow) return [bounds.lo, bounds.hi];
    const lo = Math.min(Math.max(energyWindow[0], bounds.lo), bounds.hi - MIN_WINDOW_EV);
    const hi = Math.max(Math.min(energyWindow[1], bounds.hi), lo + MIN_WINDOW_EV);
    return [lo, hi];
  }, [bounds, energyWindow]);

  const chart = useMemo(() => {
    if (!pooled || pooled.energies_eV.length === 0) return null;
    // The window is applied by rebuilding the grid over it, not by
    // clipping a full-range one: clipping would spend most of its 200
    // points outside the view and leave a tight window drawn from a
    // handful of them. Every transition still contributes to every point,
    // so the curve inside the window is unchanged -- only its resolution
    // improves. Sticks are filtered rather than rebuilt; they are the raw
    // transitions, and one either falls in the window or does not.
    //
    // Deliberately not done through xMin/xMax props on MiniLineChart:
    // that component is shared with ScanPlot and UvVisSpectrumInline, and
    // handing it only the visible data is also what rescales the
    // intensity axis to the window, which is the point of zooming in on a
    // weak feature beside a strong one.
    const { grid, y } = broadenedSpectrum(
      pooled.energies_eV, pooled.oscillator_strengths, fwhm, 200, [winLo, winHi],
    );
    // Normalized so the curve peaks at 1, exactly as
    // render_wigner_ensemble_spectrum normalizes the finished figure by the
    // total's own peak. Without this the preview and the final plot showed
    // the same spectrum on two different vertical scales: the raw sum below
    // grows with the sample count, so while a master was still running the
    // curve climbed on every poll even when its shape had settled, and the
    // number on the axis meant nothing on its own -- it is a sum of
    // overlapping Gaussians, not an oscillator strength, which is what the
    // old `f (FWHM ...)` label claimed it was.
    //
    // The sticks are divided by the SAME peak rather than by their own, for
    // the reason the server-side per-state overlays are: a series rescaled
    // to its own maximum misstates how much it contributes to the curve
    // beside it. Dividing both by one number leaves every relative height
    // exactly as it was and only changes where 1 sits on the axis.
    //
    // Deliberately the in-window peak, not the full-range one. Rebuilding
    // the grid over the selected window is already what rescales a weak
    // shoulder to fill the axis (see the comment above), which is the point
    // of the window slider; normalizing to the full-range peak would undo
    // that and leave a zoomed-in shoulder as flat as it was before.
    const peak = Math.max(...y, 0);
    const divisor = peak > 0 ? peak : 1;
    const sticks = pooled.energies_eV
      .map((e, i) => ({ x: e, y: pooled.oscillator_strengths[i] / divisor }))
      .filter((s) => s.x >= winLo && s.x <= winHi);
    return { x: grid, y: y.map((v) => v / divisor), sticks };
  }, [pooled, fwhm, winLo, winHi]);

  if (query.isLoading) {
    return <div className="text-xs text-text-muted">Loading pooled transitions...</div>;
  }
  if (query.isError || !pooled) {
    return <div className="text-xs text-status-failed">Could not load the ensemble's pooled transitions.</div>;
  }
  if (!bounds) {
    return (
      <div className="text-xs text-text-muted">
        No transitions with usable intensity to broaden yet
        {diagnostics && diagnostics.n_completed > 0 && diagnostics.n_no_intensity === diagnostics.n_completed
          ? " -- this method/engine combination doesn't report oscillator strengths."
          : "."}
      </div>
    );
  }

  const pct = (v: number) => ((v - bounds.lo) / (bounds.hi - bounds.lo || 1)) * 100;

  return (
    <div className="flex flex-col gap-2" data-testid="wigner-broadening-panel">
      {/* No "nothing in this window" fallback: the grid is rebuilt over
          whatever window is selected, so it always has points in it, and
          `bounds` above has already caught the only case that genuinely
          has nothing to draw -- an ensemble with no usable transitions. */}
      {chart && (
        <MiniLineChart
          x={chart.x} series={[{ label: "Ensemble", y: chart.y }]} sticks={chart.sticks}
          xLabel="Energy (eV)" yLabel={`Norm. intensity (FWHM ${fwhm.toFixed(2)} eV)`}
        />
      )}
      <label className="flex items-center gap-2 text-3xs text-text-muted">
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
      <div className="flex items-center gap-2 text-3xs text-text-muted">
        <span>Energy window (eV)</span>
        <div className="qc-dual-range">
          <div className="qc-dual-range-rail" />
          <div
            className="qc-dual-range-fill"
            style={{ left: `${pct(winLo)}%`, width: `${Math.max(pct(winHi) - pct(winLo), 0)}%` }}
          />
          <input
            type="range"
            min={bounds.lo}
            max={bounds.hi}
            step={WINDOW_STEP_EV}
            value={winLo}
            onChange={(e) => {
              const v = Math.min(Number(e.target.value), winHi - MIN_WINDOW_EV);
              setEnergyWindow([v, winHi]);
            }}
            className="qc-range"
            aria-label="Energy window lower bound in eV"
            data-testid="wigner-window-min"
          />
          <input
            type="range"
            min={bounds.lo}
            max={bounds.hi}
            step={WINDOW_STEP_EV}
            value={winHi}
            onChange={(e) => {
              const v = Math.max(Number(e.target.value), winLo + MIN_WINDOW_EV);
              setEnergyWindow([winLo, v]);
            }}
            className="qc-range"
            aria-label="Energy window upper bound in eV"
            data-testid="wigner-window-max"
          />
        </div>
        <span className="w-20 text-right font-mono text-text" data-testid="wigner-window-value">
          {winLo.toFixed(2)}-{winHi.toFixed(2)}
        </span>
        {energyWindow && (
          <button
            type="button"
            onClick={() => setEnergyWindow(null)}
            className="text-text-muted underline hover:text-text"
            data-testid="wigner-window-reset"
          >
            reset
          </button>
        )}
      </div>
      {diagnostics && (
        <div className="text-2xs text-text-muted">
          {diagnostics.n_transitions_pooled} transitions pooled from {diagnostics.n_completed} of{" "}
          {diagnostics.n_sub_jobs} samples
          {diagnostics.n_no_intensity > 0 && `, ${diagnostics.n_no_intensity} with no intensity data`}
          {diagnostics.n_failed_or_pending > 0 && `, ${diagnostics.n_failed_or_pending} still running or failed`}.
        </div>
      )}
    </div>
  );
}
