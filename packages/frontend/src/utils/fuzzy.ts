/**
 * Tiny dependency-free fuzzy matcher used by the command palette.
 *
 * Returns a score (higher is better) when every character of `query` appears
 * in `text` in order, or null when there is no match. Consecutive runs,
 * word-boundary hits and prefix matches are rewarded so that, e.g., "nk"
 * ranks "New Chat" above "New Knowledge Base".
 */
export interface FuzzyResult {
  score: number;
  /** Indices in `text` that matched, for optional highlighting. */
  indices: number[];
}

export function fuzzyMatch(text: string, query: string): FuzzyResult | null {
  const haystack = text.toLowerCase();
  const needle = query.toLowerCase().trim();
  if (!needle) return { score: 0, indices: [] };

  const indices: number[] = [];
  let score = 0;
  let textIndex = 0;
  let previousMatch = -1;

  for (let q = 0; q < needle.length; q++) {
    const ch = needle[q];
    if (ch === ' ') {
      previousMatch = -1;
      continue;
    }
    let found = -1;
    while (textIndex < haystack.length) {
      if (haystack[textIndex] === ch) {
        found = textIndex;
        break;
      }
      textIndex++;
    }
    if (found === -1) return null;

    indices.push(found);
    if (found === previousMatch + 1) score += 6; // consecutive run
    else if (found === 0) score += 4; // start of string
    else if (/[\s\-_/.]/.test(haystack[found - 1] ?? '')) score += 3; // word start
    else score -= Math.min(found - previousMatch - 1, 6); // gap penalty
    previousMatch = found;
    textIndex = found + 1;
  }

  if (haystack.startsWith(needle)) score += 10;
  // Prefer shorter targets when scores are otherwise close.
  score -= Math.min(Math.floor(haystack.length / 12), 6);
  return { score, indices };
}

/**
 * Rank a list of items by the best score across the supplied fields.
 */
export function fuzzyRank<T>(
  items: T[],
  query: string,
  fields: (item: T) => string[],
): { item: T; score: number; indices: number[] }[] {
  if (!query.trim()) return items.map((item) => ({ item, score: 0, indices: [] }));
  const ranked: { item: T; score: number; indices: number[] }[] = [];
  for (const item of items) {
    let best: FuzzyResult | null = null;
    for (const field of fields(item)) {
      const result = fuzzyMatch(field, query);
      if (result && (!best || result.score > best.score)) best = result;
    }
    if (best) ranked.push({ item, score: best.score, indices: best.indices });
  }
  ranked.sort((a, b) => b.score - a.score);
  return ranked;
}
