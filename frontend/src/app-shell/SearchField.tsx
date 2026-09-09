import { Search, X } from "lucide-react";
import { useEffect, useRef } from "react";

/**
 * Search that is an icon until it is wanted.
 *
 * ## Why it collapses
 *
 * Four panels each had their own near-identical always-visible search input:
 * the job manager, the knowledge base, files and plots. In three of them that
 * box is idle most of the time, and in the job manager it is actively
 * expensive: that panel is the instrument dock's only flex-1 pane, so every
 * row spent above the list is a row of jobs not shown.
 *
 * ## Why the two halves are separate exports
 *
 * The job manager puts the trigger in the section's HEADER, where there is
 * already space, and opens the input as a row in the body where it can have
 * the full width. Nothing else needs that, so {@link SearchField} composes the
 * two for the simple case.
 *
 * ## What stays true when it is closed
 *
 * The query is owned by the caller, so a collapsed field with text still in it
 * is impossible: closing clears. A panel silently filtered by a query nobody
 * can see is a list that appears to have lost rows. The trigger is tinted
 * while a query is active as a second guard against the same thing, and the
 * input will not close itself on blur while it holds text.
 */

export function SearchToggle({
  active,
  open,
  onOpenChange,
  label,
  testId,
}: {
  active: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: string;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpenChange(!open)}
      data-testid={`${testId}-open`}
      title={label}
      aria-label={label}
      aria-expanded={open}
      className={`shrink-0 rounded p-1 transition-colors hover:bg-surface-raised hover:text-text ${
        active || open ? "text-accent" : "text-text-muted"
      }`}
    >
      <Search size={14} />
    </button>
  );
}

export function SearchInput({
  value,
  onChange,
  onClose,
  placeholder,
  testId,
  countLabel,
  autoFocus = true,
}: {
  value: string;
  onChange: (value: string) => void;
  onClose: () => void;
  placeholder: string;
  /** Goes on the input itself, so existing specs keep their selector. */
  testId: string;
  /** e.g. "12 of 40 jobs", shown beside the field while a query is active. */
  countLabel?: string;
  autoFocus?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  // Escape closes; the X only clears. Pressing X is usually the start of a
  // different search, and taking the field away at that moment means finding
  // the icon and opening it again. It refocuses so typing carries straight on.
  const clear = () => {
    onChange("");
    inputRef.current?.focus();
  };
  const escape = () => {
    onChange("");
    onClose();
  };

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <div className="relative min-w-0 flex-1">
        <Search size={12} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              escape();
            }
          }}
          // Only while it is empty: closing a field that is filtering the list
          // would silently restore rows the moment focus moved elsewhere.
          onBlur={() => {
            if (!value) onClose();
          }}
          placeholder={placeholder}
          aria-label={placeholder}
          data-testid={testId}
          className="w-full rounded border border-border bg-surface py-1 pl-7 pr-6 text-2xs text-text outline-none placeholder:text-text-muted focus:border-accent"
        />
        {value && (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={clear}
            data-testid={`${testId}-clear`}
            title="Clear search"
            aria-label="Clear search"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-text-muted hover:text-text"
          >
            <X size={11} />
          </button>
        )}
      </div>
      {countLabel && <span className="shrink-0 text-3xs tabular-nums text-text-muted">{countLabel}</span>}
    </div>
  );
}

/** Trigger and input in one place, for the panels that have room for both. */
export function SearchField({
  value,
  onChange,
  open,
  onOpenChange,
  placeholder,
  testId,
  countLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  placeholder: string;
  testId: string;
  countLabel?: string;
}) {
  if (!open) {
    return (
      <SearchToggle
        active={Boolean(value)}
        open={false}
        onOpenChange={onOpenChange}
        label={placeholder}
        testId={testId}
      />
    );
  }
  return (
    <SearchInput
      value={value}
      onChange={onChange}
      onClose={() => onOpenChange(false)}
      placeholder={placeholder}
      testId={testId}
      countLabel={countLabel}
    />
  );
}
