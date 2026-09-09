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

// Iterative (not recursive) Levenshtein distance, bailing out early once
// it provably exceeds `max` -- this runs once per word token on every
// query keystroke, so a raw ORCA output with tens of thousands of tokens
// needs each comparison to stay cheap. Word-level rather than character-
// level fuzziness: a "did you mean" match against a whole mistyped word
// ("convergance" -> "convergence") reads naturally in a find bar, where
// character-subsequence fuzzy matching (VSCode command-palette style)
// would light up nearly every short substring in a large document and be
// useless as a find tool.
function levenshteinWithin(a: string, b: string, max: number): number | null {
  if (Math.abs(a.length - b.length) > max) return null;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i += 1) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      const v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      cur.push(v);
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return null; // every value in this row already exceeds max -- no cell can recover
    prev = cur;
  }
  const d = prev[b.length];
  return d <= max ? d : null;
}

function fuzzyThreshold(wordLength: number): number {
  if (wordLength <= 4) return 1;
  if (wordLength <= 9) return 2;
  return 3;
}

// Above this, fuzzy (word-by-word) scanning is skipped and only exact
// substring matches are shown -- a multi-megabyte raw output still finds
// exact matches instantly, it just doesn't also pay for a token-by-token
// edit-distance pass over the whole thing on every keystroke.
const FUZZY_MAX_TEXT_LENGTH = 2_000_000;

/**
 * Plain-text viewer with an always-visible find bar (match count,
 * next/prev, highlighting) plus Ctrl/Cmd+F support -- pressing it while
 * this component is mounted focuses the find input instead of leaving it
 * to the browser's own page-find, which can't reliably scroll a match
 * into view inside a Radix-portalled scrollable flyout.
 *
 * Fuzzy: an exact (case-insensitive) substring search always runs first;
 * for a single-word query (no whitespace) under FUZZY_MAX_TEXT_LENGTH,
 * word tokens within a small edit distance of the query are also matched
 * and highlighted, so a typo ("optmization") still finds "optimization"
 * instead of reporting no matches. A multi-word query stays exact-
 * substring-only -- fuzzy phrase matching is a different, much less
 * predictable feature, and a poor fit for a plain find bar.
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
    const qRaw = query.trim();
    if (!qRaw) return [] as { start: number; length: number }[];
    const qLower = qRaw.toLowerCase();
    const lower = text.toLowerCase();

    const exact: { start: number; length: number }[] = [];
    let from = 0;
    for (;;) {
      const i = lower.indexOf(qLower, from);
      if (i === -1) break;
      exact.push({ start: i, length: qLower.length });
      from = i + qLower.length;
    }

    // Fuzzy word matching only for a single-token query -- see this
    // component's own docstring for why a multi-word query stays
    // exact-only -- and only under FUZZY_MAX_TEXT_LENGTH, so a huge raw
    // output still finds exact matches instantly without also paying for
    // a token-by-token edit-distance pass on every keystroke.
    if (/\s/.test(qRaw) || text.length > FUZZY_MAX_TEXT_LENGTH) {
      return exact;
    }

    const exactStarts = new Set(exact.map((m) => m.start));
    const fuzzy: { start: number; length: number }[] = [];
    const threshold = fuzzyThreshold(qLower.length);
    const wordRe = /\S+/g;
    let m: RegExpExecArray | null;
    while ((m = wordRe.exec(text)) !== null) {
      if (exactStarts.has(m.index)) continue; // already an exact hit at this position
      const dist = levenshteinWithin(m[0].toLowerCase(), qLower, threshold);
      if (dist !== null) fuzzy.push({ start: m.index, length: m[0].length });
    }

    return [...exact, ...fuzzy].sort((a, b) => a.start - b.start);
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
    matches.forEach(({ start, length }, i) => {
      // A fuzzy word match can in principle overlap an exact match that
      // starts mid-word (different start position, same underlying
      // token) -- clamped rather than asserted against, so an overlap
      // degrades to "one of the two highlights is shorter" instead of a
      // negative-length slice.
      const clampedStart = Math.max(start, cursor);
      if (clampedStart > cursor) parts.push({ text: text.slice(cursor, clampedStart), match: false, active: false });
      const end = Math.max(start + length, clampedStart);
      if (end > clampedStart) {
        parts.push({ text: text.slice(clampedStart, end), match: true, active: i === activeIndex });
      }
      cursor = end;
    });
    if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false, active: false });
    return parts;
  }, [text, matches, activeIndex]);

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
          <span className="shrink-0 text-2xs tabular-nums text-text-muted">
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
      <pre className="flex-1 overflow-auto whitespace-pre-wrap font-mono text-2xs text-text-muted">
        {segments.map((seg, i) =>
          seg.match ? (
            <mark
              key={i}
              ref={(el) => {
                if (seg.active) activeMatchRef.current = el;
              }}
              className={seg.active ? "bg-accent text-on-accent" : "bg-accent/30 text-text"}
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
