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
  assert.equal(results.length, 11);
  assert.ok(results.every((r) => r.ok));
  const labels = new Set(results.map((r) => r.expected));
  for (const s of ['small', 'medium', 'big', 'huge', 'poc', 'bug', 'unattended', 'invalid_output']) assert.ok(labels.has(s), s);
});

test('a wrong expectation is reported as not ok', () => {
  const dir = copy();
  const file = join(dir, 'cases.jsonl');
  writeFileSync(file, readFileSync(file, 'utf8').replace('"expect":{"outcome":"sized","scenario":"small"', '"expect":{"outcome":"sized","scenario":"medium"'));
  const { results } = gradeCases(dir);
  assert.equal(results.find((r) => r.id === 'small-typo')?.ok, false);
});

test('an expectation outside the seven labels is a problem', () => {
  const dir = copy();
  const file = join(dir, 'cases.jsonl');
  writeFileSync(file, readFileSync(file, 'utf8').replace('"scenario":"poc","reason":"required"', '"scenario":"tiny","reason":"required"'));
  assert.ok(gradeCases(dir).problems.some((p) => p.includes('expect.scenario')));
});

test('a deleted fixture is a problem', () => {
  const dir = copy();
  rmSync(join(dir, 'fixtures/typo-readme.md'));
  assert.ok(gradeCases(dir).problems.some((p) => p.includes('typo-readme')));
});

test('cases that are all medium are a problem', () => {
  const dir = copy();
  const file = join(dir, 'cases.jsonl');
  writeFileSync(file, readFileSync(file, 'utf8').replace(/"scenario":"(small|big|huge|poc|bug|unattended)"(,"reason":"required")/g, '"scenario":"medium"$2'));
  assert.ok(gradeCases(dir).problems.some((p) => p.includes('every sized case expects medium')));
});
