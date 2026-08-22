// Hand-rolled SVG line/stick chart -- no charting library is installed in
// this project, and every consumer only needs a handful of stroked lines
// plus optional vertical sticks, which is little enough SVG to not justify
// a new dependency.
//
// P9.5: extended from a single y series to a `series` array with an
// optional legend, so ScanPlot.tsx can show every electronic state's
// energy trace live (while a pes_1d/interp_pes scan is still running AND
// once it completes) instead of falling back to the server-rendered
// artifacts.pes_plot PNG for the multi-state case -- that PNG is still
// rendered server-side (render_pes_plot, app/chemistry/spectrum.py) and
// still offered as a download, it's just no longer the only thing that can
// SHOW more than one state's curve.
const SERIES_COLORS = ["#6e8cff", "#e85b4e", "#2e9960", "#c98a1b", "#8a5fd6", "#3ba7b0"];

interface Series {
  label: string;
  y: (number | null)[];
}

interface Props {
  x: number[];
  series: Series[];
  sticks?: { x: number; y: number }[];
  xLabel: string;
  yLabel: string;
  height?: number;
  /** Force the y-axis to start at 0 (spectra/intensities). Default true.
   * Energy traces (large negative Hartree values) need false, or the whole
   * curve gets squashed against the top of the plot. */
  yBaselineZero?: boolean;
}

const WIDTH = 480;

/** The two end-of-axis tick labels. Without them the x-axis carries a name
 * but no scale, which is fine for a shape-only sparkline and not fine the
 * moment a control exists for choosing a range (WignerBroadeningPanel's
 * energy window) -- "focus on 4.5 to 6 eV" needs the axis to say where 4.5
 * and 6 are. Precision follows the span rather than being fixed: a 3 eV
 * spectrum reads better as 4.5 than 4.512, and a 0.04 A bond scan would be
 * two identical labels at one decimal. */
function fmtTick(v: number, span: number): string {
  const decimals = span >= 100 ? 0 : span >= 10 ? 1 : span >= 1 ? 2 : 3;
  return v.toFixed(decimals);
}

export function MiniLineChart({ x, series, sticks, xLabel, yLabel, height = 180, yBaselineZero = true }: Props) {
  // A single non-finite x (a null slipped through an `as number[]` cast, or
  // a NaN from upstream data) poisons Math.min/max into NaN, which silently
  // renders an empty chart with no error -- filter defensively rather than
  // trust every caller's array to be clean. A null/non-finite Y is a real,
  // meaningful GAP (a still-pending or failed scan image, see ScanPlot) --
  // kept as null and skipped only when drawing the path, not dropped from
  // the point count, so a gap breaks the line instead of silently
  // interpolating across it.
  const validXIdx = x.map((v, i) => [v, i] as const).filter(([v]) => Number.isFinite(v));
  if (validXIdx.length < 2) return null;
  const cleanX = validXIdx.map(([v]) => v);
  const cleanSeries = series.map((s) => ({
    label: s.label,
    y: validXIdx.map(([, i]) => s.y[i]),
  }));
  const cleanSticks = sticks?.filter((s) => Number.isFinite(s.x) && Number.isFinite(s.y));

  const padL = 36;
  const padB = 20;
  const padT = cleanSeries.length > 1 ? 8 + 12 : 8; // room for the legend row
  const padR = 8;
  const plotW = WIDTH - padL - padR;
  const plotH = height - padT - padB;

  const xMin = Math.min(...cleanX);
  const xMax = Math.max(...cleanX);
  const finiteY = cleanSeries.flatMap((s) => s.y).filter((v): v is number => v != null && Number.isFinite(v));
  const allY = [...finiteY, ...(cleanSticks?.map((s) => s.y) ?? [])];
  const yMin = yBaselineZero ? 0 : Math.min(...allY);
  const yMax = yBaselineZero ? Math.max(...allY, 1e-9) : Math.max(...allY);
  const ySpan = yMax - yMin || 1;
  const xSpan = xMax - xMin || 1;

  const sx = (v: number) => padL + ((v - xMin) / xSpan) * plotW;
  const sy = (v: number) => padT + plotH - ((v - yMin) / ySpan) * plotH;

  // One path per contiguous run of non-null points, per series -- a gap
  // (still-pending/failed image) breaks the line rather than being
  // interpolated across or silently dropped, matching the old single-series
  // behaviour's NaN-gap handling.
  const seriesPaths = cleanSeries.map((s) => {
    const segments: string[] = [];
    let current = "";
    cleanX.forEach((v, i) => {
      const yv = s.y[i];
      if (yv == null || !Number.isFinite(yv)) {
        if (current) segments.push(current);
        current = "";
        return;
      }
      current += `${current ? "L" : "M"}${sx(v).toFixed(2)},${sy(yv).toFixed(2)} `;
    });
    if (current) segments.push(current);
    return segments.join(" ");
  });

  return (
    <svg viewBox={`0 0 ${WIDTH} ${height}`} className="w-full text-text-muted">
      {cleanSeries.length > 1 && (
        <g>
          {cleanSeries.map((s, i) => {
            const lx = padL + i * 90;
            return (
              <g key={s.label}>
                <line x1={lx} y1={6} x2={lx + 12} y2={6} stroke={SERIES_COLORS[i % SERIES_COLORS.length]} strokeWidth={2} />
                <text x={lx + 16} y={9} fontSize={8} fill="currentColor">
                  {s.label}
                </text>
              </g>
            );
          })}
        </g>
      )}
      <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeWidth={1} opacity={0.4} />
      <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeWidth={1} opacity={0.4} />
      {cleanSticks?.map((s, i) => (
        <line
          key={i}
          x1={sx(s.x)}
          x2={sx(s.x)}
          y1={sy(0)}
          y2={sy(s.y)}
          stroke="#9aa0aa"
          strokeWidth={1.5}
          opacity={0.6}
        />
      ))}
      {seriesPaths.map((d, i) => (
        <path key={i} d={d} fill="none" stroke={SERIES_COLORS[i % SERIES_COLORS.length]} strokeWidth={1.75} />
      ))}
      <text x={padL} y={height - 12} textAnchor="start" fontSize={8} fill="currentColor" opacity={0.75}>
        {fmtTick(xMin, xSpan)}
      </text>
      <text x={padL + plotW} y={height - 12} textAnchor="end" fontSize={8} fill="currentColor" opacity={0.75}>
        {fmtTick(xMax, xSpan)}
      </text>
      <text x={padL + plotW / 2} y={height - 3} textAnchor="middle" fontSize={9} fill="currentColor">
        {xLabel}
      </text>
      <text x={10} y={padT + plotH / 2} textAnchor="middle" fontSize={9} fill="currentColor" transform={`rotate(-90 10 ${padT + plotH / 2})`}>
        {yLabel}
      </text>
    </svg>
  );
}
