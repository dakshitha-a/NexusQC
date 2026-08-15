// Shows the frequency list from a completed frequency job's summary. Rows
// are click-selectable when mode-displacement vectors are available
// (every engine's frequency job parses normal_modes now), driving a
// ModeAnimationViewer the caller renders alongside this table.
interface Props {
  frequenciesCm1: number[];
  selectedMode?: number | null;
  onSelectMode?: (index: number) => void;
}

export function VibrationTable({ frequenciesCm1, selectedMode, onSelectMode }: Props) {
  const selectable = !!onSelectMode;
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
          <tr
            key={i}
            onClick={selectable ? () => onSelectMode!(i) : undefined}
            className={`border-t border-border ${selectable ? "cursor-pointer hover:bg-surface-raised" : ""} ${
              selectedMode === i ? "bg-surface-raised" : ""
            }`}
          >
            <td className="py-1 pr-3 font-mono text-text-muted">{i + 1}</td>
            <td className={`py-1 font-mono ${f < 0 ? "text-status-failed" : "text-text"}`}>{f.toFixed(1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
