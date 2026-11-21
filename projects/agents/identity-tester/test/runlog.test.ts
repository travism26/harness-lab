import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { appendRunLog, redact } from '../src/runlog.ts';
import type { RunLogLine } from '../src/runlog.ts';

test('redact replaces every occurrence of long secrets only', () => {
  assert.equal(redact('a sk-12345678 b sk-12345678', ['sk-12345678']), 'a [redacted] b [redacted]');
  assert.equal(redact('short abc here', ['abc']), 'short abc here');
  assert.equal(redact('x', []), 'x');
});

test('appendRunLog creates the directory and appends one line per call', () => {
  const path = join(mkdtempSync(join(tmpdir(), 'log-')), 'nested', 'dir', 'log.jsonl');
  const line: RunLogLine = {
    ts: 't', agent: 'a', model: 'm', turns: 1, cost_usd: 0, outcome: 'pass', detail: '', duration_ms: 1, tools_seen: [],
  };
  appendRunLog(path, line);
  appendRunLog(path, { ...line, outcome: 'fail' });
  const lines = readFileSync(path, 'utf8').split('\n');
  assert.equal(lines.length, 3);
  assert.equal(lines[2], '');
  assert.deepEqual(JSON.parse(lines[0] as string), line);
  assert.equal(JSON.parse(lines[1] as string).outcome, 'fail');
});
