/**
 * Fuzzy subsequence matching, of the kind an editor's file finder does.
 *
 * A needle matches when its characters appear in the haystack in order but
 * not necessarily adjacently, so "cscf" finds "CASSCF" and "urcas" finds
 * "uracil SP CASSCF(12,9)/cc-pvdz (BAGEL)". Plain substring matching is a
 * special case, and scores highest, because a contiguous run collects the
 * adjacency bonus at every step.
 *
 * Ranking is the part that makes this usable rather than merely permissive.
 * Any short needle matches a great many strings by subsequence, so without
 * an ordering the good match is buried among accidental ones. Three things
 * are rewarded, in the spirit of fzf: characters matched adjacently, matches
 * that land at the start of a word, and matches that occur early.
 */

/** Non-alphanumeric characters start a new word, and so does the string. */
function isWordStart(text: string, index: number): boolean {
  if (index === 0) return true;
  const prev = text[index - 1];
  return !/[a-z0-9]/i.test(prev);
}

/**
 * Score `needle` against `haystack`, both assumed already lowercased, or
 * return null when the needle is not a subsequence of the haystack.
 *
 * Higher is better. The scale is arbitrary and only meaningful for ordering
 * candidates against one another.
 */
export function fuzzyScore(haystack: string, needle: string): number | null {
  if (needle.length === 0) return 0;
  if (needle.length > haystack.length) return null;

  let score = 0;
  let from = 0;
  let previousIndex = -1;

  for (const char of needle) {
    const index = haystack.indexOf(char, from);
    if (index === -1) return null;

    score += 1;
    if (index === previousIndex + 1) score += 6; // contiguous run
    if (isWordStart(haystack, index)) score += 4; // start of a word
    // Later matches are worth slightly less, so an early hit wins a tie.
    // Bounded so a long string does not drive the term negative.
    score -= Math.min(index, 20) * 0.1;

    previousIndex = index;
    from = index + 1;
  }
  return score;
}

/**
 * One field of a searchable record, with a weight expressing how much a
 * match in it should count. A job's name is what someone is usually looking
 * for; its id is a fallback, and fuzzy-matching hex is noisy enough that it
 * should never outrank a real name match.
 */
export interface FuzzyField {
  text: string;
  weight: number;
}

/**
 * Score a record made of several fields against a whitespace-separated
 * query. Every term must match at least one field, which is what lets
 * "casscf bagel" and "failed uracil" work without inventing a query syntax.
 * A term scores against its best field, and the record's score is the sum
 * over terms.
 */
export function fuzzyRecordScore(fields: FuzzyField[], query: string): number | null {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return 0;

  const prepared = fields.map((f) => ({ text: (f.text || "").toLowerCase(), weight: f.weight }));
  let total = 0;

  for (const term of terms) {
    let best: number | null = null;
    for (const field of prepared) {
      const raw = fuzzyScore(field.text, term);
      if (raw === null) continue;
      const weighted = raw * field.weight;
      if (best === null || weighted > best) best = weighted;
    }
    if (best === null) return null; // this term matched nothing
    total += best;
  }
  return total;
}
