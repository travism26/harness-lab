import assert from 'node:assert/strict';
import { copyFileSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import { FULL_TOOL_NAME, SERVER_NAME, runAgent, userPrompt } from '../src/run.ts';
import type { Sdk } from '../src/run.ts';

const realDir = resolve(import.meta.dirname, '..');
const FIXTURE = 'typo-readme';

type Handler = (args: { name: unknown }) => Promise<any>;
type Hook = (input: unknown) => Promise<Record<string, unknown>>;
type Ctx = { read: Handler; hook: Hook };
type Script = (ctx: Ctx) => AsyncGenerator<unknown>;

// A stand-in for the SDK. No model, no network: the script plays the model's side.
function fakeSdk(script: Script, seen: { options?: Record<string, unknown>; prompt?: string } = {}): Sdk {
  return {
    tool: (name: string, _d: string, _s: unknown, handler: Handler) => ({ name, handler }),
    createSdkMcpServer: (o: unknown) => o,
    query: (params: { prompt: string; options: Record<string, any> }) => {
      seen.options = params.options;
      seen.prompt = params.prompt;
      const tools = params.options.mcpServers[SERVER_NAME].tools as { name: string; handler: Handler }[];
      return script({ read: tools[0]!.handler, hook: params.options.hooks.PreToolUse[0].hooks[0] });
    },
  } as unknown as Sdk;
}

function tmpAgent(): string {
  const dir = mkdtempSync(join(tmpdir(), 'agent-'));
  copyFileSync(join(realDir, 'prompt.md'), join(dir, 'prompt.md'));
  copyFileSync(join(realDir, 'agent.json'), join(dir, 'agent.json'));
  return dir;
}

const success = (structured_output?: unknown, extra: Record<string, unknown> = {}) => ({
  type: 'result', subtype: 'success', is_error: false, num_turns: 3, total_cost_usd: 0.001, structured_output, ...extra,
});
const init = { type: 'system', subtype: 'init', tools: [FULL_TOOL_NAME, 'StructuredOutput'] };
const run = (script: Script, dir = tmpAgent(), seen = {}) =>
  runAgent({ sdk: fakeSdk(script, seen), agentDir: dir, fixture: FIXTURE, inputShape: {} });

// Reads the fixture, then yields the canned model output.
const reads = (result: unknown): Script =>
  async function* ({ read }) {
    yield init;
    await read({ name: FIXTURE });
    yield result;
  };

const logLines = (dir: string) => readFileSync(join(dir, 'runs/log.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));

test('a valid proposal after reading the issue is sized and is logged', async () => {
  const dir = tmpAgent();
  const seen: { options?: Record<string, unknown>; prompt?: string } = {};
  const { output, line } = await runAgent({
    sdk: fakeSdk(reads(success({ scenario: 'small', reason: 'One word.' })), seen),
    agentDir: dir, fixture: FIXTURE, inputShape: {}, now: () => new Date('2026-01-02T03:04:05.000Z'),
  });
  assert.equal(output.outcome, 'sized');
  assert.deepEqual(output.proposal, { scenario: 'small', reason: 'One word.' });
  assert.equal(output.issue_read, true);
  const lines = logLines(dir);
  assert.equal(lines.length, 1);
  assert.deepEqual(lines[0], line);
  assert.equal(lines[0].fixture, FIXTURE);
  assert.equal(lines[0].model, 'claude-haiku-5-5');
  assert.equal(seen.prompt, userPrompt(FIXTURE));
  assert.equal(seen.options?.model, 'claude-haiku-5-5');
});

test('invalid_output: a label that is not one of the seven fails the run and is logged as such', async () => {
  const dir = tmpAgent();
  const { output, line } = await run(reads(success({ scenario: 'ready-for-factory', reason: 'Looks buildable.' })), dir);
  assert.equal(output.outcome, 'invalid_output');
  assert.match(output.detail, /ready-for-factory/);
  assert.equal(output.proposal, null);
  assert.equal(line.outcome, 'invalid_output');
  const lines = logLines(dir);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].outcome, 'invalid_output');
});

test('invalid_output: an empty reason, a missing reason and unparseable output', async () => {
  for (const bad of [{ scenario: 'small', reason: '' }, { scenario: 'small' }, 'small', 42, { nonsense: true }]) {
    const dir = tmpAgent();
    const { output } = await run(reads(success(bad)), dir);
    assert.equal(output.outcome, 'invalid_output', JSON.stringify(bad));
    assert.equal(output.proposal, null);
    assert.equal(logLines(dir)[0].outcome, 'invalid_output');
  }
});

test('invalid_output: success with no structured output at all', async () => {
  assert.equal((await run(reads(success(undefined)))).output.outcome, 'invalid_output');
});

test('a proposal when the issue was never read is tool_not_run', async () => {
  const sdk = async function* () {
    yield init;
    yield success({ scenario: 'small', reason: 'Guessed.' });
  };
  const { output } = await run(sdk);
  assert.equal(output.outcome, 'tool_not_run');
  assert.equal(output.proposal, null);
});

test('reading a different fixture than the one asked for does not count as a read', async () => {
  const sdk: Script = async function* ({ read }) {
    yield init;
    await read({ name: 'overnight-run' });
    yield success({ scenario: 'small', reason: 'r' });
  };
  assert.equal((await run(sdk)).output.outcome, 'tool_not_run');
});

test('the tool handler returns the fixture text, and an error for an escape', async () => {
  let good: any;
  const bad: any[] = [];
  const sdk: Script = async function* ({ read }) {
    good = await read({ name: FIXTURE });
    for (const name of ['../../package', '/etc/passwd', '..', 'typo-readme.md', undefined]) bad.push(await read({ name }));
    yield success(undefined);
  };
  await run(sdk);
  assert.equal(good.isError, false);
  assert.match(good.content[0].text, /Fix a typo/);
  for (const b of bad) {
    assert.equal(b.isError, true);
    assert.doesNotMatch(b.content[0].text, /"name"|"version"/);
  }
});

test('the hook denies other tools, and the run is denied_tool despite a valid proposal', async () => {
  let decision: Record<string, any> = {};
  const sdk: Script = async function* ({ read, hook }) {
    yield init;
    await read({ name: FIXTURE });
    decision = await hook({ hook_event_name: 'PreToolUse', tool_name: 'Read', tool_input: {}, tool_use_id: 'x' });
    yield success({ scenario: 'small', reason: 'r' });
  };
  const { output } = await run(sdk);
  assert.equal(decision.hookSpecificOutput.permissionDecision, 'deny');
  assert.equal(output.outcome, 'denied_tool');
  assert.equal(output.detail, 'denied: Read');
  assert.equal(output.proposal, null);
});

test('the hook allows the issue tool and StructuredOutput only', async () => {
  const answers: unknown[] = [];
  const sdk: Script = async function* ({ hook }) {
    for (const tool_name of ['StructuredOutput', FULL_TOOL_NAME, 'Bash', 'WebFetch']) {
      answers.push(await hook({ hook_event_name: 'PreToolUse', tool_name, tool_input: {}, tool_use_id: 'x' }));
    }
    yield success(undefined);
  };
  await run(sdk);
  assert.deepEqual(answers.slice(0, 2), [{}, {}]);
  assert.equal((answers[2] as any).hookSpecificOutput.permissionDecision, 'deny');
  assert.equal((answers[3] as any).hookSpecificOutput.permissionDecision, 'deny');
});

test('caps: max turns and max budget are failed runs, even when a throw follows', async () => {
  const mk = (subtype: string): Script =>
    async function* () {
      yield { type: 'result', subtype, is_error: true, num_turns: 12, total_cost_usd: 0.1 };
      throw new Error('process exited with code 1');
    };
  assert.equal((await run(mk('error_max_turns'))).output.outcome, 'max_turns');
  assert.equal((await run(mk('error_max_budget_usd'))).output.outcome, 'max_budget');
  assert.equal((await run(mk('error_max_structured_output_retries'))).output.outcome, 'invalid_output');
});

test('a throw before any result is error, and a secret in it is redacted everywhere', async () => {
  const secret = 'sk-' + 'ant-' + 'not-a-real-key-123'; // built here so projects/agents/check does not read this file as holding a key
  const dir = tmpAgent();
  const sdk: Script = async function* () {
    yield init;
    throw new Error(`auth failed for ${secret}`);
  };
  const { output } = await runAgent({ sdk: fakeSdk(sdk), agentDir: dir, fixture: FIXTURE, inputShape: {}, secrets: [secret] });
  assert.equal(output.outcome, 'error');
  assert.ok(!JSON.stringify(output).includes(secret));
  assert.ok(!readFileSync(join(dir, 'runs/log.jsonl'), 'utf8').includes(secret));
});

test('config drift in allowedTools rejects', async () => {
  const dir = tmpAgent();
  const c = JSON.parse(readFileSync(join(dir, 'agent.json'), 'utf8')) as Record<string, unknown>;
  c.allowedTools = [FULL_TOOL_NAME, 'mcp__issues__extra'];
  writeFileSync(join(dir, 'agent.json'), JSON.stringify(c));
  await assert.rejects(run(reads(success(undefined)), dir), /allowedTools/);
});
