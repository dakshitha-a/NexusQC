import * as Popover from "@radix-ui/react-popover";
import { Archive, Check, SlidersHorizontal } from "lucide-react";
import { SearchToggle } from "../app-shell/SearchField";
import { useJobFilterStore } from "../lib/jobFilterStore";

/**
 * The job manager's controls, rendered in the section HEADER rather than
 * inside the panel.
 *
 * ## Why they moved
 *
 * A permanent search input and a "Show archived" checkbox sat on a row at the
 * top of the panel body, plus a second row for the result count whenever a
 * query was active. The job manager is the instrument dock's only flex-1 pane,
 * which makes it the one place in the app where a row of chrome is measured in
 * jobs you cannot see, and those rows were there whether or not anybody was
 * filtering. The header already had empty space beside the title.
 *
 * The search INPUT still opens as a row in the body, where it can have the
 * full width; only the trigger lives here. See SearchField.
 *
 * ## The status and engine filters are new
 *
 * The panel had no way to narrow by anything except text, so "show me what
 * failed" meant reading the dots. An empty selection means no narrowing, not
 * "show nothing", which is the reading a first-time user has of an untouched
 * filter.
 */

const STATUSES = ["running", "pending", "completed", "failed", "cancelled"] as const;
const ENGINES = ["pyscf", "orca", "bagel"] as const;

const STATUS_DOT: Record<(typeof STATUSES)[number], string> = {
  running: "bg-status-running",
  pending: "bg-status-pending",
  completed: "bg-status-completed",
  failed: "bg-status-failed",
  cancelled: "bg-status-cancelled",
};

const ENGINE_DOT: Record<(typeof ENGINES)[number], string> = {
  pyscf: "bg-engine-pyscf",
  orca: "bg-engine-orca",
  bagel: "bg-engine-bagel",
};

export function JobManagerToolbar() {
  const { query, searchOpen, showArchived, statuses, engines } = useJobFilterStore();
  const { setSearchOpen, setShowArchived, toggleStatus, toggleEngine, clearFilters } = useJobFilterStore();
  const filterCount = statuses.length + engines.length;

  const row = (
    label: string,
    values: readonly string[],
    selected: string[],
    onToggle: (v: string) => void,
    dots: Record<string, string>,
  ) => (
    <div>
      <div className="px-2 pb-1 pt-1.5 text-3xs font-semibold uppercase tracking-wide text-text-muted">{label}</div>
      {values.map((v) => {
        const on = selected.includes(v);
        return (
          <button
            key={v}
            onClick={() => onToggle(v)}
            aria-pressed={on}
            data-testid={`jobmanager-filter-${v}`}
            className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-2xs text-text-muted transition-colors hover:bg-surface-raised hover:text-text"
          >
            <span className={`size-2 shrink-0 rounded-full ${dots[v]}`} />
            <span className="flex-1 capitalize">{v}</span>
            {on && <Check size={11} className="text-accent" />}
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="flex shrink-0 items-center gap-0.5">
      <SearchToggle
        active={Boolean(query)}
        open={searchOpen}
        onOpenChange={setSearchOpen}
        label="Search jobs"
        testId="jobmanager-search"
      />
      <Popover.Root>
        <Popover.Trigger asChild>
          <button
            type="button"
            data-testid="jobmanager-filters"
            title="Narrow by status or engine"
            aria-label="Narrow by status or engine"
            className={`relative shrink-0 rounded p-1 transition-colors hover:bg-surface-raised hover:text-text ${
              filterCount ? "text-accent" : "text-text-muted"
            }`}
          >
            <SlidersHorizontal size={14} />
            {filterCount > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex size-3 items-center justify-center rounded-full bg-accent text-[8px] font-semibold text-on-accent">
                {filterCount}
              </span>
            )}
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            side="bottom"
            align="end"
            sideOffset={6}
            data-testid="jobmanager-filter-menu"
            className="z-50 w-44 rounded-md border border-border bg-surface p-1 shadow-2xl data-[state=open]:animate-fade-in"
          >
            {row("Status", STATUSES, statuses, toggleStatus, STATUS_DOT)}
            {row("Engine", ENGINES, engines, toggleEngine, ENGINE_DOT)}
            {filterCount > 0 && (
              <button
                onClick={clearFilters}
                data-testid="jobmanager-filters-clear"
                className="mt-1 w-full rounded border-t border-border px-2 py-1 text-left text-2xs text-text-muted hover:text-text"
              >
                Clear {filterCount} filter{filterCount === 1 ? "" : "s"}
              </button>
            )}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {/* Was a checkbox with a "Show archived" label beside it, which cost the
          width of the label on the one row that could least afford it. The
          pressed state is on the button, so a screen reader still gets the
          same information the label carried. */}
      <button
        type="button"
        onClick={() => setShowArchived(!showArchived)}
        aria-pressed={showArchived}
        data-testid="jobmanager-show-archived"
        title={
          showArchived
            ? "Hide jobs that have been filed into a project archive"
            : "Also list jobs that have been filed into a project archive"
        }
        aria-label="Show archived jobs"
        className={`shrink-0 rounded p-1 transition-colors hover:bg-surface-raised hover:text-text ${
          showArchived ? "text-accent" : "text-text-muted"
        }`}
      >
        <Archive size={14} />
      </button>
    </div>
  );
}
