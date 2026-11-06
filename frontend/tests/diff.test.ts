import assert from 'node:assert/strict';
import test from 'node:test';
import { diffLines } from '../src/utils/diff.ts';

test('插入步骤不把后续未变内容全部标为改动', () => {
  const changes = diffLines(['取出', '放好'], ['取出', '打开', '放好']);
  assert.deepEqual(changes.filter((line) => line.kind !== 'same'), [
    { kind: 'added', text: '打开', before: null, after: 2 },
  ]);
});

test('重排和删除重复步骤可区分，顺序可还原', () => {
  for (const [before, after] of [
    [['取出', '放好', '取出'], ['放好', '取出', '取出']],
    [['取出', '取出'], ['取出']],
    [[], ['取出']],
    [['取出'], []],
  ]) {
    const lines = diffLines(before, after);
    assert.deepEqual(lines.filter((line) => line.kind !== 'added').map((line) => line.text), before);
    assert.deepEqual(lines.filter((line) => line.kind !== 'removed').map((line) => line.text), after);
    assert.ok(lines.some((line) => line.kind !== 'same'));
  }
});
