import { MiniLineChart } from "./MiniLineChart";

export function OptimizationEnergyPlot({ energiesHartree }: { energiesHartree: number[] }) {
  if (energiesHartree.length < 2) return null;
  const x = energiesHartree.map((_, i) => i + 1);
  return (
    <MiniLineChart
      x={x}
      series={[{ label: "Energy", y: energiesHartree }]}
      xLabel="Optimization step"
      yLabel="Energy (Eh)"
      yBaselineZero={false}
    />
  );
}
