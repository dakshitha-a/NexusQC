// Hand-rolled SVG line/stick chart -- no charting library is installed in
// this project, and both consumers (UvVisSpectrumInline, OptimizationEnergyPlot)
// only need a single filled/stroked line plus optional vertical sticks, which
// is little enough SVG to not justify a new dependency.
interface Props {
  x: number[];
  y: number[];
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

export function MiniLineChart({ x, y, sticks, xLabel, yLabel, height = 180, yBaselineZero = true }: Props) {
  // A single non-finite x/y (a null slipped through an `as number[]` cast,
  // or a NaN from upstream data) poisons Math.min/max into NaN, which
  // silently renders an empty chart with no error -- filter defensively
  // rather than trust every caller's array to be clean.
  const points = x.map((v, i) => [v, y[i]] as const).filter(([xv, yv]) => Number.isFinite(xv) && Number.isFinite(yv));
  if (points.length < 2) return null;
  const cleanX = points.map((p) => p[0]);
  const cleanY = points.map((p) => p[1]);
  const cleanSticks = sticks?.filter((s) => Number.isFinite(s.x) && Number.isFinite(s.y));

  const padL = 36;
  const padB = 20;
  const padT = 8;
  const padR = 8;
  const plotW = WIDTH - padL - padR;
  const plotH = height - padT - padB;

  const xMin = Math.min(...cleanX);
  const xMax = Math.max(...cleanX);
  const allY = [...cleanY, ...(cleanSticks?.map((s) => s.y) ?? [])];
  const yMin = yBaselineZero ? 0 : Math.min(...allY);
  const yMax = yBaselineZero ? Math.max(...allY, 1e-9) : Math.max(...allY);
  const ySpan = yMax - yMin || 1;
  const xSpan = xMax - xMin || 1;

  const sx = (v: number) => padL + ((v - xMin) / xSpan) * plotW;
  const sy = (v: number) => padT + plotH - ((v - yMin) / ySpan) * plotH;

  const path = cleanX.map((v, i) => `${i === 0 ? "M" : "L"}${sx(v).toFixed(2)},${sy(cleanY[i]).toFixed(2)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${WIDTH} ${height}`} className="w-full text-text-muted">
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
      <path d={path} fill="none" stroke="#6e8cff" strokeWidth={1.75} />
      <text x={padL + plotW / 2} y={height - 3} textAnchor="middle" fontSize={9} fill="currentColor">
        {xLabel}
      </text>
      <text x={10} y={padT + plotH / 2} textAnchor="middle" fontSize={9} fill="currentColor" transform={`rotate(-90 10 ${padT + plotH / 2})`}>
        {yLabel}
      </text>
    </svg>
  );
}
