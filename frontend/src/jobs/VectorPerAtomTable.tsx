// Shared by GradientSection and NacSection (JobDetailDrawer.tsx) -- both
// render the exact same shape of data: one 3-vector per atom plus a norm,
// the gradient_hartree_per_bohr/nac_hartree_per_bohr fields every engine's
// run_gradient/run_nac writes (app/chemistry/jobs/{pyscf,orca,bagel}_runner.py).
const fmt = (v: number) => v.toFixed(6);

export function VectorPerAtomTable({
  vectors,
  symbols,
}: {
  vectors: number[][];
  symbols: string[] | undefined;
}) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-text-muted">
          <th className="py-1 pr-3 font-normal">Atom</th>
          <th className="py-1 pr-3 font-normal">x</th>
          <th className="py-1 pr-3 font-normal">y</th>
          <th className="py-1 font-normal">z</th>
        </tr>
      </thead>
      <tbody>
        {vectors.map((row, i) => (
          <tr key={i} className="border-t border-border">
            <td className="py-1 pr-3 font-mono text-text-muted">
              {i + 1}
              {symbols?.[i] ? ` ${symbols[i]}` : ""}
            </td>
            <td className="py-1 pr-3 font-mono">{fmt(row[0])}</td>
            <td className="py-1 pr-3 font-mono">{fmt(row[1])}</td>
            <td className="py-1 font-mono">{fmt(row[2])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
