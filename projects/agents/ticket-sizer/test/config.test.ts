import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { buildOptions, loadConfig, loadPrompt } from '../src/config.ts';

const realDir = resolve(import.meta.dirname, '..');
const parts = { cwd: realDir, mcpServers: {}, hooks: {}, outputSchema: { type: 'object' } };

test('buildOptions on the real folder', () => {
  const o = buildOptions(loadConfig(realDir), loadPrompt(realDir), parts);
  assert.equal(o.model, 'claude-haiku-5-5');
  assert.deepEqual(o.settingSources, []);
  assert.equal(o.permissionMode, 'dontAsk');
  assert.ok((o.maxTurns ?? 99) <= 12);
  assert.ok((o.maxBudgetUsd ?? 99) <= 0.1);
  assert.equal(o.effort, 'low');
  assert.deepEqual(o.tools, []);
  assert.deepEqual(o.allowedTools, ['mcp__issues__read_issue']);
  for (const name of ['Bash', 'Write', 'Edit', 'NotebookEdit', 'Read', 'WebFetch']) assert.ok(o.disallowedTools?.includes(name), name);
  assert.equal(o.strictMcpConfig, true);
  assert.equal(o.persistSession, false);
});
