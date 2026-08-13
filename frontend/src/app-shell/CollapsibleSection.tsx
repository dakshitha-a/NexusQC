import { ChevronDown, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
  /** Extra content in the header, right-aligned before the chevron (e.g. a badge). */
  headerExtra?: ReactNode;
  className?: string;
}

export function CollapsibleSection({ title, collapsed, onToggle, children, headerExtra, className }: Props) {
  return (
    <div className={`flex min-h-0 flex-col ${className ?? ""}`}>
      <div className="flex shrink-0 items-center justify-between gap-2 px-3 py-2">
        <button
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-xs font-medium uppercase tracking-wide text-text-muted hover:text-text transition-colors"
        >
          {collapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
          {title}
        </button>
        {headerExtra}
      </div>
      {!collapsed && <div className="flex min-h-0 flex-1 flex-col">{children}</div>}
    </div>
  );
}
