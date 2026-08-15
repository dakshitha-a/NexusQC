import { ChevronDown, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
  /** Extra content in the header, right-aligned before the chevron (e.g. a badge). */
  headerExtra?: ReactNode;
  /** Second header line below the title row (e.g. a storage-usage badge) --
   * like headerExtra, always shown regardless of collapsed state. */
  subHeader?: ReactNode;
  className?: string;
}

export function CollapsibleSection({ title, collapsed, onToggle, children, headerExtra, subHeader, className }: Props) {
  return (
    <div className={`flex min-h-0 flex-col ${className ?? ""}`}>
      <div className="flex shrink-0 flex-col gap-1 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <button
            onClick={onToggle}
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-xs font-medium uppercase tracking-wide text-text-muted hover:text-text transition-colors"
          >
            {collapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
            {title}
          </button>
          {headerExtra}
        </div>
        {subHeader && <div className="pl-[19px]">{subHeader}</div>}
      </div>
      {!collapsed && <div className="flex min-h-0 flex-1 flex-col">{children}</div>}
    </div>
  );
}
