export interface DiffLine {
  kind: 'same' | 'added' | 'removed';
  text: string;
  before: number | null;
  after: number | null;
}

export function diffLines(before: string[], after: string[]): DiffLine[] {
  const lengths = Array.from({ length: before.length + 1 }, () => new Uint32Array(after.length + 1));
  for (let i = before.length - 1; i >= 0; i--) {
    for (let j = after.length - 1; j >= 0; j--) {
      lengths[i][j] = before[i] === after[j] ? lengths[i + 1][j + 1] + 1
        : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    }
  }
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < before.length || j < after.length) {
    if (i < before.length && j < after.length && before[i] === after[j]) {
      result.push({ kind: 'same', text: before[i], before: ++i, after: ++j });
    } else if (i < before.length && (j === after.length || lengths[i + 1][j] >= lengths[i][j + 1])) {
      result.push({ kind: 'removed', text: before[i], before: ++i, after: null });
    } else {
      result.push({ kind: 'added', text: after[j], before: null, after: ++j });
    }
  }
  return result;
}
