import assert from 'node:assert/strict';
import { copyFileSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import type { ToolName, ToolRecord } from '../src/commands.ts';
import { SERVER_NAME, USER_PROMPT, runAgent } from '../src/run.ts';
import type { Sdk } from '../src/run.ts';

const realDir = resolve(import.meta.dirname, '..');
const CHECK = 'mcp__identity__run_check';
const TOUR = 'mcp__identity__run_tour';

type Handler = () => Promise<unknown>;
type Hook = (input: unknown) => Promise<Record<string, unknown>>;
type Ctx = { handlers: Record<string, Handler>; hook: Hook; options: Record<string, unknown> };
type Script = (ctx: Ctx) => AsyncGenerator<unknown>;

function fakeSdk(script: Script, seen: { options?: Record<string, unknown>; prompt?: string } = {}): Sdk {
  return {
    tool: (name: string, _d: string, _s: unknown, handler: Handler) => ({ name, handler }),
    createSdkMcpServer: (o: unknown) => o,
    query: (params: { prompt: string; options: Record<string, any> }) => {
      seen.options = params.options;
      seen.prompt = params.prompt;
      const tools = params.options.mcpServers[SERVER_NAME].tools as { name: string; handler: Handler }[];
      const handlers = Object.fromEntries(tools.map((t) => [t.name, t.handler]));
      return script({ handlers, hook: params.options.hooks.PreToolUse[0].hooks[0], options: params.options });
    },
  } as unknown as Sdk;
}

function tmpAgent(mutate?: (c: Record<string, unknown>) => void): string {
  const dir = mkdtempSync(join(tmpdir(), 'agent-'));
  copyFileSync(join(realDir, 'prompt.md'), join(dir, 'prompt.md'));
  const c = JSON.parse(readFileSync(join(realDir, 'agent.json'), 'utf8')) as Record<string, unknown>;
  mutate?.(c);
  writeFileSync(join(dir, 'agent.json'), JSON.stringify(c));
  return dir;
}

const exits = (check: number, tour: number) => async (tool: ToolName): Promise<ToolRecord> => ({
  tool, exit_code: tool === 'run_check' ? check : tour, timed_out: false, output: `${tool} output`,
});
const report = (check: string, tour: string, overall: string) => ({
  check: { status: check, evidence: 'check evidence' }, tour: { status: tour, evidence: 'tour evidence' }, overall, summary: 'sum',
});
const success = (structured_output?: unknown, extra: Record<string, unknown> = {}) => ({
  type: 'result', subtype: 'success', is_error: false, num_turns: 4, total_cost_usd: 0.003, structured_output, ...extra,
});
const init = { type: 'system', subtype: 'init', tools: [CHECK, TOUR, 'StructuredOutput'] };

// Calls both tools, then yields the given result.
const runsBoth = (result: unknown): Script =>
  async function* ({ handlers }) {
    yield init;
    await handlers.run_check!();
    await handlers.run_tour!();
    yield result;
  };

const logLines = (dir: string) =>
  readFileSync(join(dir, 'runs/log.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));

test('both pass with an honest report is pass', async () => {
  const dir = tmpAgent();
  const seen: { options?: Record<string, unknown>; prompt?: string } = {};
  const { output, line } = await runAgent({
    sdk: fakeSdk(runsBoth(success(report('pass', 'pass', 'pass'))), seen),
    agentDir: dir, execute: exits(0, 0), now: () => new Date('2026-01-02T03:04:05.000Z'),
  });
  assert.equal(output.outcome, 'pass');
  assert.equal(output.report?.overall, 'pass');
  assert.deepEqual(output.commands.run_check, { exit_code: 0, status: 'pass' });
  const lines = logLines(dir);
  assert.equal(lines.length, 1);
  assert.deepEqual(lines[0], line);
  assert.equal(lines[0].model, 'claude-haiku-5-5');
  assert.equal(lines[0].turns, 4);
  assert.equal(lines[0].cost_usd, 0.003);
  assert.equal(lines[0].ts, '2026-01-02T03:04:05.000Z');
  assert.deepEqual(lines[0].tools_seen, [CHECK, TOUR, 'StructuredOutput']);
  assert.equal(seen.options?.model, 'claude-haiku-5-5');
  assert.equal(seen.prompt, USER_PROMPT);
});

test('a failing check with an honest report is fail and the report is kept', async () => {
  const { output } = await runAgent({
    sdk: fakeSdk(runsBoth(success(report('fail', 'pass', 'fail')))), agentDir: tmpAgent(), execute: exits(1, 0),
  });
  assert.equal(output.outcome, 'fail');
  assert.equal(output.detail, 'run_check exited 1');
  assert.equal(output.report?.check.evidence, 'check evidence');
  assert.deepEqual(output.commands.run_check, { exit_code: 1, status: 'fail' });
});

test('a dishonest report is report_mismatch and is dropped', async () => {
  const { output } = await runAgent({
    sdk: fakeSdk(runsBoth(success(report('pass', 'pass', 'pass')))), agentDir: tmpAgent(), execute: exits(1, 0),
  });
  assert.equal(output.outcome, 'report_mismatch');
  assert.equal(output.report, null);
});

test('a tour that was never called is tool_not_run', async () => {
  const sdk = fakeSdk(async function* ({ handlers }) {
    yield init;
    await handlers.run_check!();
    yield success(report('pass', 'pass', 'pass'));
  });
  const { output } = await runAgent({ sdk, agentDir: tmpAgent(), execute: exits(0, 0) });
  assert.equal(output.outcome, 'tool_not_run');
  assert.equal(output.commands.run_tour, null);
});

test('the hook denies other tools and the run is denied_tool despite success', async () => {
  let decision: Record<string, any> = {};
  const sdk = fakeSdk(async function* ({ handlers, hook }) {
    yield init;
    await handlers.run_check!();
    await handlers.run_tour!();
    decision = await hook({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: {}, tool_use_id: 'x' });
    yield success(report('pass', 'pass', 'pass'));
  });
  const { output } = await runAgent({ sdk, agentDir: tmpAgent(), execute: exits(0, 0) });
  assert.equal(decision.hookSpecificOutput.permissionDecision, 'deny');
  assert.equal(decision.hookSpecificOutput.hookEventName, 'PreToolUse');
  assert.equal(output.outcome, 'denied_tool');
  assert.equal(output.detail, 'denied: Bash');
  assert.equal(output.report, null);
});

test('the hook allows the two tools and StructuredOutput', async () => {
  const answers: unknown[] = [];
  const sdk = fakeSdk(async function* ({ hook }) {
    for (const tool_name of ['StructuredOutput', CHECK, TOUR]) {
      answers.push(await hook({ hook_event_name: 'PreToolUse', tool_name, tool_input: {}, tool_use_id: 'x' }));
    }
    yield success(undefined);
  });
  await runAgent({ sdk, agentDir: tmpAgent(), execute: exits(0, 0) });
  assert.deepEqual(answers, [{}, {}, {}]);
});

test('permission_denials on the result is denied_tool', async () => {
  const sdk = fakeSdk(runsBoth(success(report('pass', 'pass', 'pass'), { permission_denials: [{ tool_name: 'Read' }] })));
  const { output } = await runAgent({ sdk, agentDir: tmpAgent(), execute: exits(0, 0) });
  assert.equal(output.outcome, 'denied_tool');
  assert.equal(output.detail, 'denied: Read');
});

test('error result followed by a throw keeps the result', async () => {
  const sdk = fakeSdk(async function* () {
    yield { type: 'result', subtype: 'error_max_turns', is_error: true, num_turns: 12, total_cost_usd: 0.01 };
    throw new Error('process exited with code 1');
  });
  const { output, line } = await runAgent({ sdk, agentDir: tmpAgent(), execute: exits(0, 0) });
  assert.equal(output.outcome, 'max_turns');
  assert.equal(line.turns, 12);
});

test('max budget and structured output retries', async () => {
  const mk = (subtype: string) =>
    fakeSdk(async function* () {
      yield { type: 'result', subtype, is_error: true, num_turns: 2, total_cost_usd: 0.1 };
    });
  const a = await runAgent({ sdk: mk('error_max_budget_usd'), agentDir: tmpAgent(), execute: exits(0, 0) });
  assert.equal(a.output.outcome, 'max_budget');
  const b = await runAgent({ sdk: mk('error_max_structured_output_retries'), agentDir: tmpAgent(), execute: exits(0, 0) });
  assert.equal(b.output.outcome, 'invalid_output');
});

test('success without structured_output is invalid_output', async () => {
  const { output } = await runAgent({ sdk: fakeSdk(runsBoth(success(undefined))), agentDir: tmpAgent(), execute: exits(0, 0) });
  assert.equal(output.outcome, 'invalid_output');
});

test('a throw before any result is error, and a secret in it is redacted everywhere', async () => {
  const secret = 'sk-' + 'ant-' + 'not-a-real-key-123'; // built here so projects/agents/check does not read this file as holding a key
  const dir = tmpAgent();
  const sdk = fakeSdk(async function* () {
    yield init;
    throw new Error(`auth failed for ${secret}`);
  });
  const { output } = await runAgent({ sdk, agentDir: dir, execute: exits(0, 0), secrets: [secret] });
  assert.equal(output.outcome, 'error');
  assert.ok(!JSON.stringify(output).includes(secret));
  assert.ok(!readFileSync(join(dir, 'runs/log.jsonl'), 'utf8').includes(secret));
  assert.match(output.detail, /\[redacted\]/);
});

test('a secret in the report text is redacted when the report is kept', async () => {
  const secret = 'sk-' + 'ant-' + 'not-a-real-key-123'; // built here so projects/agents/check does not read this file as holding a key
  const r = report('pass', 'pass', 'pass');
  r.check.evidence = `leaked ${secret}`;
  const { output } = await runAgent({
    sdk: fakeSdk(runsBoth(success(r))), agentDir: tmpAgent(), execute: exits(0, 0), secrets: [secret],
  });
  assert.equal(output.outcome, 'pass');
  assert.ok(!JSON.stringify(output).includes(secret));
});

test('config drift in allowedTools rejects', async () => {
  const dir = tmpAgent((c) => (c.allowedTools = [CHECK, TOUR, 'mcp__identity__extra']));
  await assert.rejects(runAgent({ sdk: fakeSdk(runsBoth(success())), agentDir: dir, execute: exits(0, 0) }), /allowedTools/);
});

test('a tool handler returns the record as JSON and flags a null exit as an error', async () => {
  let ok: any;
  let bad: any;
  const sdk = fakeSdk(async function* ({ handlers }) {
    ok = await handlers.run_check!();
    bad = await handlers.run_tour!();
    yield success(undefined);
  });
  await runAgent({
    sdk, agentDir: tmpAgent(),
    execute: async (tool) => ({ tool, exit_code: tool === 'run_check' ? 1 : null, timed_out: tool === 'run_tour', output: 'o' }),
  });
  assert.equal(ok.isError, false);
  assert.deepEqual(JSON.parse(ok.content[0].text), { exit_code: 1, timed_out: false, output: 'o' });
  assert.equal(bad.isError, true);
});
