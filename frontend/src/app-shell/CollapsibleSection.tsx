import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

interface HeaderAction {
  /** Shown when `active` is false. */
  icon: ReactNode;
  /** Shown when `active` is true, e.g. an X where the idle state is a +. */
  activeIcon?: ReactNode;
  label: string;
  active?: boolean;
  /** Called with the state the caller should move to. See the note below on
   *  why the component decides this rather than the caller toggling. */
  onActivate: (open: boolean) => void;
  testId?: string;
}

interface Props {
  title: string;
  /** Stable hook for tests, appended to `section-`. Defaults to a slug of the
   * title, so every section gets one whether or not a caller supplies it --
   * the previous state of this component had no testid and no
   * `aria-expanded`, which made it both untestable and, more importantly,
   * unreadable to a screen reader: the only signal that a section was
   * collapsed was which chevron glyph happened to be rendered. */
  testId?: string;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
  /**
   * A button in the header that does something to the section's contents:
   * "add a source", "upload a file", "new project".
   *
   * ## The bug this exists to fix
   *
   * Each of those was a plain button in `headerExtra` doing
   * `setAdding((a) => !a)`, and the form it revealed lives inside `children`,
   * which is unmounted while the section is collapsed. All three of those
   * sections default to collapsed, so the first click on a fresh install
   * flipped the icon from + to X and showed nothing at all. The second click
   * flipped it back. Nothing about that was visible from reading either file
   * on its own, which is why it survived so long.
   *
   * So the section expands itself first and only then calls back. And it
   * passes the state to move to rather than letting the caller toggle: from
   * collapsed, the answer is always "open", never "whatever the opposite of
   * the stale value is".
   *
   * The old buttons also each carried an `e.stopPropagation()` that did
   * nothing, since `headerExtra` is a sibling of the toggle button rather
   * than a child of it, so the click never had a path to bubble into it.
   */
  action?: HeaderAction;
  /** Extra content in the header, right-aligned before the action (e.g. a badge). */
  headerExtra?: ReactNode;
  /** Second header line below the title row (e.g. a totals line) -- like
   * headerExtra, always shown regardless of collapsed state. */
  subHeader?: ReactNode;
  /** Keeps the header in view while the body scrolls under it. On for the
   * sidebar's stacked sections, where the whole point is that you can always
   * see where you are. */
  stickyHeader?: boolean;
  /** Makes the body its own scroll container. On for the sidebar's sections,
   * which are capped at a max-height and have to scroll past it rather than
   * push whatever is below them off the screen. Off by default because the
   * instrument dock's panels already scroll themselves, and a second scroller
   * wrapped around one of those is a scrollbar inside a scrollbar. */
  scrollBody?: boolean;
  className?: string;
}

/**
 * A titled, collapsible section. Used for every drawer in the sidebar and the
 * instrument panel.
 *
 * ## Why the body does not animate open
 *
 * It was tried. Every mechanism for transitioning to an unmeasured height
 * (a grid-template-rows 0fr->1fr wrapper, or Radix's Accordion, which is
 * already a dependency) works by giving the body a measured or animatable
 * height. Several of these sections are not height-driven: the Job manager is
 * the instrument panel's only flex-1 child with a min-height floor, the
 * conversation list is the sidebar's, and both scroll internally. Pinning
 * their height to their content is precisely the failure the comments in
 * RightDock.tsx describe, where a panel squeezed to zero and disappeared
 * instead of the dock gaining a scrollbar.
 *
 * Keeping the body mounted while collapsed would also restart every query
 * inside it, including the job list's four-second poll.
 *
 * So the motion budget goes where it costs no layout: the chevron turns, the
 * action icon turns, and the header tints under the pointer.
 */
export function CollapsibleSection({
  title,
  collapsed,
  onToggle,
  children,
  action,
  headerExtra,
  subHeader,
  stickyHeader,
  scrollBody,
  className,
  testId,
}: Props) {
  const slug = testId ?? title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  const panelId = `section-${slug}-panel`;
  return (
    <div className={`flex min-h-0 flex-col ${className ?? ""}`}>
      <div
        className={`flex shrink-0 flex-col gap-1 px-3 py-2 ${
          stickyHeader ? "sticky top-0 z-10 bg-surface" : ""
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <button
            onClick={onToggle}
            data-testid={`section-${slug}-toggle`}
            aria-expanded={!collapsed}
            aria-controls={panelId}
            className="group flex min-w-0 flex-1 items-center gap-1.5 text-left text-xs font-medium uppercase tracking-wide text-text-muted transition-colors hover:text-text"
          >
            <ChevronRight
              size={13}
              className={`shrink-0 transition-transform duration-fast ease-standard ${
                collapsed ? "" : "rotate-90"
              }`}
            />
            <span className="truncate">{title}</span>
          </button>
          {headerExtra}
          {action && (
            <button
              onClick={() => {
                // Expand first. This is the whole point of the prop: the form
                // the callback reveals lives in the body, which is unmounted
                // while collapsed, so calling back without opening the section
                // is exactly the bug being fixed.
                if (collapsed) onToggle();
                action.onActivate(collapsed ? true : !action.active);
              }}
              data-testid={action.testId}
              title={action.label}
              aria-label={action.label}
              className="shrink-0 rounded p-1 text-text-muted transition-colors hover:bg-surface-raised hover:text-text"
            >
              {action.active && action.activeIcon ? action.activeIcon : action.icon}
            </button>
          )}
        </div>
        {subHeader && <div className="pl-[19px]">{subHeader}</div>}
      </div>
      {!collapsed && (
        <div
          id={panelId}
          data-testid={`section-${slug}-panel`}
          className={`flex min-h-0 flex-1 flex-col ${scrollBody ? "overflow-y-auto" : ""}`}
        >
          {children}
        </div>
      )}
    </div>
  );
}
