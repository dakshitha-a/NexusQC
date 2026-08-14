import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";

// Lets a parent Flyout intercept Escape (via Dialog.Content's
// onEscapeKeyDown, see Flyout.tsx) to clear an in-progress search instead
// of closing the whole panel -- SearchableText owns the query state
// internally, so the parent needs this handle to reach in and check/clear
// it from its own escape-key callback.
export interface SearchableTextHandle {
  hasQuery: () => boolean;
  clear: () => void;
}

/**
 * Plain-text viewer with an always-visible find bar (match count,
 * next/prev, highlighting) plus Ctrl/Cmd+F support -- pressing it while
 * this component is mounted focuses the find input instead of leaving it
 * to the browser's own page-find, which can't reliably scroll a match
 * into view inside a Radix-portalled scrollable flyout.
 */
export const SearchableText = forwardRef<SearchableTextHandle, { text: string }>(function SearchableText(
  { text },
  ref,
) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeMatchRef = useRef<HTMLElement | null>(null);

  useImperativeHandle(
    ref,
    () => ({
      hasQuery: () => query.trim().length > 0,
      clear: () => setQuery(""),
    }),
    [query],
  );

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [] as number[];
    const lower = text.toLowerCase();
    const idxs: number[] = [];
    let from = 0;
    for (;;) {
      const i = lower.indexOf(q, from);
      if (i === -1) break;
      idxs.push(i);
      from = i + q.length;
    }
    return idxs;
  }, [text, query]);

  useEffect(() => setActiveIndex(0), [query]);

  useEffect(() => {
    activeMatchRef.current?.scrollIntoView({ block: "center" });
  }, [activeIndex, matches.length]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const goNext = () => matches.length > 0 && setActiveIndex((i) => (i + 1) % matches.length);
  const goPrev = () => matches.length > 0 && setActiveIndex((i) => (i - 1 + matches.length) % matches.length);

  const segments = useMemo(() => {
    if (matches.length === 0) return [{ text, match: false, active: false }];
    const parts: { text: string; match: boolean; active: boolean }[] = [];
    let cursor = 0;
    matches.forEach((start, i) => {
      if (start > cursor) parts.push({ text: text.slice(cursor, start), match: false, active: false });
      parts.push({ text: text.slice(start, start + query.trim().length), match: true, active: i === activeIndex });
      cursor = start + query.trim().length;
    });
    if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false, active: false });
    return parts;
  }, [text, matches, query, activeIndex]);

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="sticky top-0 z-10 flex shrink-0 items-center gap-1.5 rounded border border-border bg-surface-raised px-2 py-1.5">
        <Search size={13} className="shrink-0 text-text-muted" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (e.shiftKey) goPrev();
              else goNext();
            } else if (e.key === "Escape" && query) {
              // The parent Flyout's onEscapeKeyDown (see Flyout.tsx) is
              // what actually stops Radix from also closing the panel on
              // this same keypress -- this just clears the query itself.
              setQuery("");
            }
          }}
          placeholder="Find in text... (Ctrl+F)"
          className="min-w-0 flex-1 bg-transparent text-xs text-text placeholder:text-text-muted outline-none"
        />
        {query.trim() && (
          <span className="shrink-0 text-[11px] tabular-nums text-text-muted">
            {matches.length === 0 ? "0/0" : `${activeIndex + 1}/${matches.length}`}
          </span>
        )}
        <button
          onClick={goPrev}
          disabled={matches.length === 0}
          className="shrink-0 rounded p-0.5 text-text-muted hover:bg-surface hover:text-text disabled:opacity-30"
          title="Previous match"
        >
          <ChevronUp size={13} />
        </button>
        <button
          onClick={goNext}
          disabled={matches.length === 0}
          className="shrink-0 rounded p-0.5 text-text-muted hover:bg-surface hover:text-text disabled:opacity-30"
          title="Next match"
        >
          <ChevronDown size={13} />
        </button>
        {query && (
          <button
            onClick={() => setQuery("")}
            className="shrink-0 rounded p-0.5 text-text-muted hover:bg-surface hover:text-text"
            title="Clear search"
          >
            <X size={13} />
          </button>
        )}
      </div>
      <pre className="flex-1 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-text-muted">
        {segments.map((seg, i) =>
          seg.match ? (
            <mark
              key={i}
              ref={(el) => {
                if (seg.active) activeMatchRef.current = el;
              }}
              className={seg.active ? "bg-accent text-white" : "bg-accent/30 text-text"}
            >
              {seg.text}
            </mark>
          ) : (
            <span key={i}>{seg.text}</span>
          ),
        )}
      </pre>
    </div>
  );
});
