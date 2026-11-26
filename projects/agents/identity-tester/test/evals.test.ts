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
  assert.equal(results.length, 13);
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

test('a tools entry outside the allowlist, or an extra records key, is a problem', () => {
  for (const edit of [
    (t: string) => t.replace('"id":"all-pass",', '"id":"all-pass","tools":["Bash"],'),
    (t: string) => t.replace('"id":"all-pass","records":{', '"id":"all-pass","records":{"read_file":"fixtures/tour-pass.json",'),
  ]) {
    const dir = copy();
    const file = join(dir, 'cases.jsonl');
    writeFileSync(file, edit(readFileSync(file, 'utf8')));
    assert.ok(gradeCases(dir).problems.length > 0);
  }
});

test('removing any of the four synthetic cases is a problem', () => {
  for (const id of ['synthetic-clean', 'synthetic-job-change', 'synthetic-canary-absent', 'synthetic-canary-echoed']) {
    const dir = copy();
    const file = join(dir, 'cases.jsonl');
    const kept = readFileSync(file, 'utf8').split('\n').filter((l) => !l.includes(`"id":"${id}"`));
    writeFileSync(file, kept.join('\n'));
    assert.ok(gradeCases(dir).problems.some((p) => p.includes(id)), id);
  }
});

test('the synthetic fixtures hold no URL', () => {
  for (const f of ['check-synthetic-clean', 'check-synthetic-job-change', 'check-synthetic-canary', 'tour-synthetic']) {
    assert.ok(!readFileSync(join(realEvals, `fixtures/${f}.json`), 'utf8').includes('://'), f);
  }
});

test('all-pass is still the first pass line', () => {
  const first = readFileSync(join(realEvals, 'cases.jsonl'), 'utf8').split('\n').find((l) => l.includes('"outcome":"pass"'));
  assert.ok(first?.includes('"id":"all-pass"'));
});
