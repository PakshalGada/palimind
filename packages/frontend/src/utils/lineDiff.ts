/**
 * Small line diff used by the version compare view.
 *
 * Uses a bounded LCS table for typical artifacts and a common-prefix/suffix
 * fallback for very large files so the UI never allocates an enormous matrix.
 */

export interface DiffCell {
  number: number;
  text: string;
  kind: 'same' | 'add' | 'remove';
}

export interface DiffRow {
  left?: DiffCell;
  right?: DiffCell;
}

export interface LineDiff {
  rows: DiffRow[];
  added: number;
  removed: number;
}

const MAX_DIFF_CELLS = 250_000;

function splitLines(value: string): string[] {
  return value.replace(/\r\n/g, '\n').split('\n');
}

function fallbackDiff(before: string[], after: string[]): LineDiff {
  let prefix = 0;
  while (
    prefix < before.length &&
    prefix < after.length &&
    before[prefix] === after[prefix]
  ) {
    prefix += 1;
  }

  let suffix = 0;
  while (
    suffix < before.length - prefix &&
    suffix < after.length - prefix &&
    before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  ) {
    suffix += 1;
  }

  const rows: DiffRow[] = [];
  let leftNo = 1;
  let rightNo = 1;

  for (let i = 0; i < prefix; i += 1) {
    rows.push({
      left: { number: leftNo++, text: before[i], kind: 'same' },
      right: { number: rightNo++, text: after[i], kind: 'same' },
    });
  }

  const leftMiddle = before.slice(prefix, before.length - suffix);
  const rightMiddle = after.slice(prefix, after.length - suffix);
  let added = 0;
  let removed = 0;
  for (let i = 0; i < Math.max(leftMiddle.length, rightMiddle.length); i += 1) {
    const leftText = leftMiddle[i];
    const rightText = rightMiddle[i];
    const row: DiffRow = {};
    if (leftText !== undefined) {
      row.left = { number: leftNo++, text: leftText, kind: 'remove' };
      removed += 1;
    }
    if (rightText !== undefined) {
      row.right = { number: rightNo++, text: rightText, kind: 'add' };
      added += 1;
    }
    rows.push(row);
  }

  for (let i = before.length - suffix; i < before.length; i += 1) {
    rows.push({
      left: { number: leftNo++, text: before[i], kind: 'same' },
      right: { number: rightNo++, text: after[i], kind: 'same' },
    });
  }

  return { rows, added, removed };
}

/** Produce aligned rows: additions on the right, deletions on the left. */
export function diffLines(before: string, after: string): LineDiff {
  const a = splitLines(before);
  const b = splitLines(after);

  if (a.length * b.length > MAX_DIFF_CELLS) {
    return fallbackDiff(a, b);
  }

  const n = a.length;
  const m = b.length;
  const dp: Uint32Array[] = Array.from(
    { length: n + 1 },
    () => new Uint32Array(m + 1),
  );

  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] =
        a[i] === b[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  let leftNo = 1;
  let rightNo = 1;
  let added = 0;
  let removed = 0;

  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({
        left: { number: leftNo++, text: a[i], kind: 'same' },
        right: { number: rightNo++, text: b[j], kind: 'same' },
      });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({
        left: { number: leftNo++, text: a[i], kind: 'remove' },
      });
      removed += 1;
      i += 1;
    } else {
      rows.push({
        right: { number: rightNo++, text: b[j], kind: 'add' },
      });
      added += 1;
      j += 1;
    }
  }

  while (i < n) {
    rows.push({
      left: { number: leftNo++, text: a[i], kind: 'remove' },
    });
    removed += 1;
    i += 1;
  }
  while (j < m) {
    rows.push({
      right: { number: rightNo++, text: b[j], kind: 'add' },
    });
    added += 1;
    j += 1;
  }

  return { rows, added, removed };
}
