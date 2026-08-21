import { useEffect, useRef } from "react";

// Shows the frequency list from a completed frequency job's summary. Rows
// are click-selectable when mode-displacement vectors are available
// (every engine's frequency job parses normal_modes now), driving a
// ModeAnimationViewer the caller renders alongside this table.
//
// F-026: which rows are painted as imaginary is the BACKEND's decision,
// delivered as `imaginary_flags` alongside the frequency list. This used to
// be re-derived here as a bare `f < 0`, which is a different rule from the
// one the summary's own n_imaginary_frequencies count uses -- so a -5.9
// cm^-1 near-zero rotational mode was rendered in "imaginary" red directly
// above a summary line reading `n_imaginary_frequencies: 0`. Two answers to
// the same chemically load-bearing question, on the same screen.
interface Props {
  frequenciesCm1: number[];
  /** Parallel to frequenciesCm1. Absent on any frequency job that
   * completed before this field existed -- those result.json files are on
   * disk and are never rewritten, so the threshold is re-applied here for
   * them rather than silently falling back to the sign rule this fix
   * exists to remove. */
  imaginaryFlags?: boolean[];
  /** The threshold the backend used, echoed so a legacy job is judged by
   * the same number rather than a second hardcoded copy of it. */
  imaginaryThresholdCm1?: number;
  selectedMode?: number | null;
  onSelectMode?: (index: number) => void;
}

const DEFAULT_IMAGINARY_THRESHOLD_CM1 = 50;

export function VibrationTable({
  frequenciesCm1,
  imaginaryFlags,
  imaginaryThresholdCm1,
  selectedMode,
  onSelectMode,
}: Props) {
  const selectable = !!onSelectMode;
  const selectedRowRef = useRef<HTMLTableRowElement>(null);

  // The mode scrubber beside this table can move the selection to a row that
  // is scrolled out of sight; leaving the highlight off-screen would let the
  // table and the animation visibly disagree about which mode is showing.
  // "nearest" only scrolls when the row really is out of view, so clicking a
  // visible row never shifts the list under the cursor.
  useEffect(() => {
    selectedRowRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedMode]);
  const threshold = imaginaryThresholdCm1 ?? DEFAULT_IMAGINARY_THRESHOLD_CM1;
  const isImaginary = (f: number, i: number) =>
    imaginaryFlags?.[i] ?? f < -threshold;

  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 bg-surface">
        <tr className="text-left text-text-muted">
          <th className="py-1 pr-3 font-normal">Mode</th>
          <th className="py-1 font-normal">Frequency (cm⁻¹)</th>
        </tr>
      </thead>
      <tbody>
        {frequenciesCm1.map((f, i) => (
          <tr
            key={i}
            ref={selectedMode === i ? selectedRowRef : undefined}
            data-testid={`vibration-row-${i}`}
            onClick={selectable ? () => onSelectMode!(i) : undefined}
            className={`border-t border-border ${selectable ? "cursor-pointer hover:bg-surface-raised" : ""} ${
              selectedMode === i ? "bg-surface-raised" : ""
            }`}
          >
            <td className="py-1 pr-3 font-mono text-text-muted">{i + 1}</td>
            <td
              className={`py-1 font-mono ${isImaginary(f, i) ? "text-status-failed" : "text-text"}`}
              title={
                isImaginary(f, i)
                  ? `Imaginary mode (below -${threshold} cm⁻¹)`
                  : undefined
              }
            >
              {f?.toFixed(1) ?? "--"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
