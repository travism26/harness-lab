import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import { buildOptions, loadConfig, loadPrompt } from '../src/config.ts';

const realDir = resolve(import.meta.dirname, '..');
const parts = { cwd: realDir, mcpServers: {}, hooks: {}, outputSchema: { type: 'object' } };

test('buildOptions on the real folder', () => {
  const o = buildOptions(loadConfig(realDir), loadPrompt(realDir), parts);
  assert.equal(o.model, 'claude-haiku-5-5');
  assert.deepEqual(o.settingSources, []);
  assert.equal(o.permissionMode, 'dontAsk');
  assert.equal(o.maxTurns, 12);
  assert.equal(o.maxBudgetUsd, 0.1);
  assert.equal(o.effort, 'medium');
  assert.deepEqual(o.tools, []);
  assert.deepEqual(o.allowedTools, ['mcp__identity__run_check', 'mcp__identity__run_tour']);
  for (const name of ['Bash', 'Write', 'Edit', 'NotebookEdit']) assert.ok(o.disallowedTools?.includes(name), name);
  assert.equal(o.strictMcpConfig, true);
  assert.equal(o.persistSession, false);
  assert.equal(o.outputFormat?.type, 'json_schema');
  assert.deepEqual(Object.keys(o).sort(), [
    'allowedTools', 'cwd', 'disallowedTools', 'effort', 'hooks', 'maxBudgetUsd', 'maxTurns', 'mcpServers',
    'model', 'outputFormat', 'permissionMode', 'persistSession', 'settingSources', 'strictMcpConfig',
    'systemPrompt', 'tools',
  ]);
});

function dirWith(change: (c: Record<string, unknown>) => void): string {
  const c = JSON.parse(JSON.stringify(loadConfig(realDir))) as Record<string, unknown>;
  change(c);
  const dir = mkdtempSync(join(tmpdir(), 'cfg-'));
  writeFileSync(join(dir, 'agent.json'), JSON.stringify(c));
  return dir;
}

test('loadConfig rejects a missing maxBudgetUsd', () => {
  assert.throws(() => loadConfig(dirWith((c) => delete c.maxBudgetUsd)), /maxBudgetUsd/);
});

test('loadConfig rejects non-empty settingSources', () => {
  assert.throws(() => loadConfig(dirWith((c) => (c.settingSources = ['project']))), /settingSources/);
});

test("loadConfig rejects permissionMode other than 'dontAsk'", () => {
  assert.throws(() => loadConfig(dirWith((c) => (c.permissionMode = 'default'))), /permissionMode/);
});
