import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import { gradeCases } from '../evals/grade.ts';

const realEvals = resolve(import.meta.dirname, '../evals');
const copy = () => {
  const dir = mkdtempSync(join(tmpdir(), 'evals-'));
  cpSync(realEvals, dir, { recursive: true });
  return dir;
};

test('the real evals are all ok with no problems', () => {
  const { results, problems } = gradeCases(realEvals);
  assert.deepEqual(problems, []);
  assert.equal(results.length, 9);
  assert.ok(results.every((r) => r.ok));
});

test('a flipped expectation is reported as not ok', () => {
  const dir = copy();
  const file = join(dir, 'cases.jsonl');
  writeFileSync(file, readFileSync(file, 'utf8').replace('"expect":{"outcome":"pass"}', '"expect":{"outcome":"fail"}'));
  const { results } = gradeCases(dir);
  assert.equal(results.find((r) => r.id === 'all-pass')?.ok, false);
});

test('a deleted fixture is a problem', () => {
  const dir = copy();
  rmSync(join(dir, 'fixtures/tour-pass.json'));
  assert.ok(gradeCases(dir).problems.some((p) => p.includes('tour-pass.json')));
});
