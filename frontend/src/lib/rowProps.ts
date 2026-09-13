import type { KeyboardEvent } from "react";

/**
 * One owner for "this row is a control".
 *
 * Every selection row in the app was built as a styled `div`, `li` or `tr`
 * with an `onClick` and nothing else, so none of them could be reached from
 * the keyboard: not a conversation in the sidebar, not a job row in either job
 * list, not a plot card, and, worse, not an orbital row or a vibrational mode
 * row. Those last two are not chrome. They are how a user chooses which
 * orbital the isosurface shows and which normal mode animates, so the
 * scientific selection path itself was mouse-only.
 *
 * `FrameScrubber` already had the shape and its own comment records the lesson
 * that matters here: `tabIndex` alone only makes an element reachable by Tab,
 * and a key handler has to come with it or arriving there achieves nothing.
 *
 * Three details that are easy to get wrong:
 *
 * - **Space scrolls the page** unless the handler prevents the default, and a
 *   row that scrolls the list away from itself when you try to select it is
 *   worse than one that does nothing.
 * - **A row often contains its own buttons** (delete, download, a menu). The
 *   handler ignores a key event that did not originate on the row itself, so
 *   Enter on an inner button does not also fire the row's action.
 * - **Focus has to be visible.** A focus ring is not decoration once the rows
 *   are tabbable; without it a keyboard user cannot tell where they are. The
 *   ring class is returned here rather than left to each call site.
 *
 * `role` differs by element and that is deliberate. A `<tr>` given
 * `role="button"` stops being a table row, which takes the row and column
 * relationships away from a screen reader and is a worse trade than the one it
 * makes. Table rows therefore stay rows and carry `aria-selected` to say which
 * one is chosen; a `div` or `li` that is really a button says so.
 */

type RowKind = "row" | "button";

export type RowActivationProps = {
  tabIndex: 0;
  role?: "button";
  "aria-selected"?: boolean;
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void;
  className: string;
};

/** Tailwind classes every activatable row shares. Append, do not replace. */
export const ROW_FOCUS_CLASS =
  "outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-accent";

export function rowProps(
  onActivate: () => void,
  opts: { kind?: RowKind; selected?: boolean } = {},
): RowActivationProps {
  const kind = opts.kind ?? "row";
  const props: RowActivationProps = {
    tabIndex: 0,
    onKeyDown: (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      // An inner control's own Enter or Space is its business.
      if (e.target !== e.currentTarget) return;
      e.preventDefault();
      onActivate();
    },
    className: ROW_FOCUS_CLASS,
  };
  if (kind === "button") props.role = "button";
  if (opts.selected !== undefined) props["aria-selected"] = opts.selected;
  return props;
}
