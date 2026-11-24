import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { FIXTURES_DIR, MAX_FIXTURE_CHARS, readFixture } from '../src/fixtures.ts';

// <tmp>/outside.md holds a secret-looking file; <tmp>/fixtures is the confined directory.
function sandbox() {
  const root = mkdtempSync(join(tmpdir(), 'fixtures-'));
  const dir = join(root, 'fixtures');
  mkdirSync(dir);
  writeFileSync(join(dir, 'good.md'), '# an issue\n');
  writeFileSync(join(root, 'outside.md'), 'OUTSIDE');
  return { root, dir };
}

test('a real fixture is read', () => {
  assert.deepEqual(readFixture('good', sandbox().dir), { ok: true, text: '# an issue\n' });
  assert.equal(readFixture('typo-readme', FIXTURES_DIR).ok, true);
});

test('path escapes are rejected: separators, "..", absolute paths, extensions', () => {
  const { dir } = sandbox();
  for (const bad of ['../outside', '..', '../outside.md', 'a/../good', 'sub/good', '/etc/passwd', '/tmp/x', 'good.md', '.hidden', 'good\\x', 'C:\\x', '', 'good\0', '-', ' good']) {
    const r = readFixture(bad, dir);
    assert.equal(r.ok, false, JSON.stringify(bad));
    if (!r.ok) assert.ok(!r.error.includes('OUTSIDE'));
  }
});

test('non-string names are rejected', () => {
  const { dir } = sandbox();
  for (const bad of [undefined, null, 1, {}, ['good']]) assert.equal(readFixture(bad, dir).ok, false);
});

test('a symlink out of the directory is rejected', () => {
  const { root, dir } = sandbox();
  symlinkSync(join(root, 'outside.md'), join(dir, 'escape.md'));
  const r = readFixture('escape', dir);
  assert.equal(r.ok, false);
  assert.ok(!JSON.stringify(r).includes('OUTSIDE'));
});

test('a symlink to another fixture inside the directory is also rejected', () => {
  const { dir } = sandbox();
  symlinkSync(join(dir, 'good.md'), join(dir, 'alias.md'));
  assert.equal(readFixture('alias', dir).ok, false);
});

test('a directory named like a fixture is rejected, and so is a missing one', () => {
  const { dir } = sandbox();
  mkdirSync(join(dir, 'folder.md'));
  assert.equal(readFixture('folder', dir).ok, false);
  assert.equal(readFixture('missing', dir).ok, false);
});

test('an oversized fixture is rejected', () => {
  const { dir } = sandbox();
  writeFileSync(join(dir, 'big.md'), 'x'.repeat(MAX_FIXTURE_CHARS + 1));
  assert.equal(readFixture('big', dir).ok, false);
});
