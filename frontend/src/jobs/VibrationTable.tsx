// Shows the frequency list from a completed frequency job's summary.
// Deliberately data-only (no 3D displacement-arrow animation) -- that
// would duplicate a large chunk of the MoleculeViewer's imperative 3Dmol
// machinery for comparatively low payoff here; flagged as a reasonable
// follow-up rather than built now given the size of this rewrite.
export function VibrationTable({ frequenciesCm1 }: { frequenciesCm1: number[] }) {
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-text-muted">
          <th className="py-1 pr-3 font-normal">Mode</th>
          <th className="py-1 font-normal">Frequency (cm⁻¹)</th>
        </tr>
      </thead>
      <tbody>
        {frequenciesCm1.map((f, i) => (
          <tr key={i} className="border-t border-border">
            <td className="py-1 pr-3 font-mono text-text-muted">{i + 1}</td>
            <td className={`py-1 font-mono ${f < 0 ? "text-status-failed" : "text-text"}`}>{f.toFixed(1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
