import { ChevronDown, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

/**
 * A table row that opens to reveal a detail panel spanning the full table
 * width.
 *
 * Every table in the admin console was `overflow-x-auto` at `text-[11px]`,
 * with the Actions column last. Inside a dialog narrower than the table, that
 * column is simply off-screen -- which is how a working Delete-account button
 * came to be reported as a missing feature. Moving detail and actions into a
 * row that expands downward means neither can be pushed out of view by a long
 * username or a narrow window, because the panel's width is the table's width.
 *
 * The whole row is the toggle, so there is no small chevron to hit.
 */
export function ExpandableRow({
  expanded,
  onToggle,
  cells,
  detail,
  testId,
  tone,
}: {
  expanded: boolean;
  onToggle: () => void;
  /** Collapsed-state cells, already <td>-less: each becomes one column. */
  cells: ReactNode[];
  detail: ReactNode;
  testId?: string;
  /** Optional row tint, e.g. to mark an archived or suspended item. */
  tone?: string;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        data-testid={testId}
        className={`cursor-pointer border-b border-border last:border-b-0 hover:bg-surface-raised/60 ${tone ?? ""}`}
      >
        <td className="w-5 py-1.5 pl-2 align-top text-text-muted">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </td>
        {cells.map((c, i) => (
          <td key={i} className="px-2 py-1.5 align-top">
            {c}
          </td>
        ))}
      </tr>
      {expanded && (
        <tr className="border-b border-border last:border-b-0">
          {/* Deliberately larger than the 11px table around it: this panel is
              for reading, and the density that suits a scannable row is the
              wrong density for a paragraph of report text or a JSON blob. */}
          <td colSpan={cells.length + 1} className="bg-bg/40 px-4 py-3 text-xs">
            {detail}
          </td>
        </tr>
      )}
    </>
  );
}

/** Label/value pair for an expanded row's detail panel. */
export function DetailField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-2 py-0.5">
      <span className="w-32 shrink-0 text-text-muted">{label}</span>
      <span className="min-w-0 flex-1 break-words text-text">{children}</span>
    </div>
  );
}
