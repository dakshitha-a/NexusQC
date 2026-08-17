import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

export type SortDirection = "asc" | "desc";

/** How to read a sort value out of a row. Returning null/undefined sorts the
 *  row to the end regardless of direction -- "never logged in" and "never
 *  redeemed" are absences, not the smallest possible date. */
export type SortAccessors<T> = Record<string, (row: T) => string | number | null | undefined>;

/**
 * Click-to-sort for the admin console's tables.
 *
 * None of them could be sorted at all, and the invites table in particular
 * only ever grows -- revocation is a soft flag and invites are never deleted,
 * so an admin looking for one specific invite was scanning an unordered wall
 * of spent rows.
 *
 * The default key should match whatever order the server already returns, so
 * the first render doesn't visibly reshuffle.
 */
export function useSortableRows<T>(
  rows: T[],
  accessors: SortAccessors<T>,
  defaultKey: string,
  defaultDirection: SortDirection = "desc",
) {
  const [key, setKey] = useState(defaultKey);
  const [direction, setDirection] = useState<SortDirection>(defaultDirection);

  const sorted = useMemo(() => {
    const get = accessors[key];
    if (!get) return rows;
    // Copy first: Array.prototype.sort mutates, and `rows` is react-query's
    // cached array -- sorting it in place would reorder the cache itself and
    // desynchronise any other component reading the same query key.
    return [...rows].sort((a, b) => {
      const av = get(a);
      const bv = get(b);
      const aMissing = av === null || av === undefined || av === "";
      const bMissing = bv === null || bv === undefined || bv === "";
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" });
      return direction === "asc" ? cmp : -cmp;
    });
  }, [rows, accessors, key, direction]);

  /** A clickable <th>. First click on a new column sorts descending (the
   *  useful default for dates -- newest first); clicking the active column
   *  flips it. */
  const header = (label: ReactNode, sortKey?: string, className = "") => {
    if (!sortKey || !accessors[sortKey]) {
      return <th className={`px-2 py-1.5 font-medium ${className}`}>{label}</th>;
    }
    const active = key === sortKey;
    return (
      <th className={`px-2 py-1.5 font-medium ${className}`}>
        <button
          onClick={() => {
            if (active) setDirection((d) => (d === "asc" ? "desc" : "asc"));
            else {
              setKey(sortKey);
              setDirection("desc");
            }
          }}
          data-testid={`sort-${sortKey}`}
          className={`flex items-center gap-1 hover:text-text ${active ? "text-text" : ""}`}
        >
          {label}
          {active && (direction === "asc" ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
        </button>
      </th>
    );
  };

  return { rows: sorted, header, sortKey: key, direction };
}
