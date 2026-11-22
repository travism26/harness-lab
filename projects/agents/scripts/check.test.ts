import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { PLACEHOLDER, REQUIRED_FILES, checkRoot, validateRunLogLine } from './check.ts';

const AGENTS_DIR = join(import.meta.dirname, '..');
const TEMPLATE = join(AGENTS_DIR, '_template');

type Obj = Record<string, unknown>;

const SAMPLE_LINE = {
  ts: '2026-11-21T21:00:00.000Z',
  agent: 'sample-agent',
  model: 'claude-haiku-5-5',
  turns: 4,
  cost_usd: 0.003,
  outcome: 'pass',
  detail: '',
  duration_ms: 41200,
};

function writeJson(path: string, value: unknown): void {
  writeFileSync(path, JSON.stringify(value, null, 2));
}

function build(): { root: string; agent: string } {
  const root = mkdtempSync(join(tmpdir(), 'agents-check-'));
  writeFileSync(join(root, 'README.md'), '# agents\n');
  cpSync(TEMPLATE, join(root, '_template'), { recursive: true });
  const agent = join(root, 'sample-agent');
  cpSync(TEMPLATE, agent, { recursive: true });
  const config = JSON.parse(readFileSync(join(agent, 'agent.json'), 'utf8')) as Obj;
  config.name = 'sample-agent';
  config.job = 'Run the sample thing and report whether it passed.';
  config.allowedTools = ['mcp__sample__run_thing'];
  writeJson(join(agent, 'agent.json'), config);
  writeFileSync(join(agent, 'prompt.md'), 'Call run_thing once and report pass or fail.\n');
  writeFileSync(join(agent, 'README.md'), '# sample-agent\n\nRuns the sample thing.\n');
  writeFileSync(join(agent, 'evals/cases.jsonl'), JSON.stringify({ id: 'case-a', records: {}, report: {}, expect: { outcome: 'pass' } }) + '\n');
  writeFileSync(join(agent, 'runs/sample.jsonl'), JSON.stringify(SAMPLE_LINE) + '\n');
  writeJson(join(agent, 'package.json'), { name: 'sample-agent', dependencies: { '@anthropic-ai/claude-agent-sdk': '0.3.330' } });
  writeJson(join(agent, 'package-lock.json'), { lockfileVersion: 3, packages: { 'node_modules/@anthropic-ai/claude-agent-sdk': { version: '0.3.330' } } });
  mkdirSync(join(agent, 'src'), { recursive: true });
  writeFileSync(join(agent, 'src/main.ts'), "console.log('sample');\n");
  writeFileSync(join(agent, 'evals/grade.ts'), "console.log('ok');\n");
  return { root, agent };
}

function problemsFor(mutate: (t: { root: string; agent: string }) => void): string[] {
  const t = build();
  try {
    mutate(t);
    return checkRoot(t.root);
  } finally {
    rmSync(t.root, { recursive: true, force: true });
  }
}

function editConfig(t: { agent: string }, change: (c: Obj) => void): void {
  const p = join(t.agent, 'agent.json');
  const c = JSON.parse(readFileSync(p, 'utf8')) as Obj;
  change(c);
  writeJson(p, c);
}

function expectProblem(problems: string[], re: RegExp): void {
  assert.ok(problems.some((p) => re.test(p)), `expected a problem matching ${re}, got:\n${problems.join('\n')}`);
}

test('baseline tree has no problems', () => {
  assert.deepEqual(problemsFor(() => {}), []);
});

test('template and root layout', () => {
  expectProblem(problemsFor((t) => rmSync(join(t.root, '_template/prompt.md'))), /^_template\/prompt\.md: missing/);
  expectProblem(problemsFor((t) => rmSync(join(t.root, '_template'), { recursive: true })), /^_template: missing/);
  expectProblem(problemsFor((t) => rmSync(join(t.root, 'README.md'))), /^README\.md: missing/);
});

for (const file of REQUIRED_FILES) {
  test(`deleting ${file} from an agent is reported`, () => {
    const escaped = file.replace(/[.]/g, '\\.');
    expectProblem(problemsFor((t) => rmSync(join(t.agent, file))), new RegExp(`^sample-agent/${escaped}: missing`));
  });
}

const configCases: [string, (c: Obj) => void, RegExp][] = [
  ['wrong model', (c) => { c.model = 'claude-haiku-4-5'; }, /agent\.json: model must be/],
  ['maxTurns removed', (c) => { delete c.maxTurns; }, /maxTurns/],
  ['maxTurns 0', (c) => { c.maxTurns = 0; }, /maxTurns/],
  ['maxTurns 31', (c) => { c.maxTurns = 31; }, /maxTurns/],
  ['maxBudgetUsd removed', (c) => { delete c.maxBudgetUsd; }, /maxBudgetUsd/],
  ['maxBudgetUsd 5', (c) => { c.maxBudgetUsd = 5; }, /maxBudgetUsd/],
  ['effort high', (c) => { c.effort = 'high'; }, /effort/],
  ['settingSources project', (c) => { c.settingSources = ['project']; }, /settingSources/],
  ['permissionMode default', (c) => { c.permissionMode = 'default'; }, /permissionMode/],
  ['permissionMode bypassPermissions', (c) => { c.permissionMode = 'bypassPermissions'; }, /permissionMode/],
  ['disallowedTools without Bash', (c) => { c.disallowedTools = ['Write', 'Edit', 'NotebookEdit']; }, /disallowedTools must include Bash/],
  ['disallowedTools without Write', (c) => { c.disallowedTools = ['Bash', 'Edit', 'NotebookEdit']; }, /disallowedTools must include Write/],
  ['disallowedTools without Edit', (c) => { c.disallowedTools = ['Bash', 'Write', 'NotebookEdit']; }, /disallowedTools must include Edit/],
  ['allowedTools has Bash', (c) => { c.allowedTools = ['mcp__sample__run_thing', 'Bash']; }, /allowedTools must not include Bash/],
  ['allowedTools Read not in tools', (c) => { c.allowedTools = ['Read']; c.tools = []; }, /allowedTools entry Read/],
  ['allowedTools glob', (c) => { c.allowedTools = ['mcp__*']; }, /allowedTools entry mcp__\*/],
  ['tools lists Write', (c) => { c.tools = ['Write']; }, /tools must not list Write/],
  ['name differs from folder', (c) => { c.name = 'other-name'; }, /name must equal the folder name/],
  ['runLog not under runs/', (c) => { c.runLog = 'log.txt'; }, /runLog/],
];

for (const [label, change, re] of configCases) {
  test(`agent.json: ${label}`, () => {
    expectProblem(problemsFor((t) => editConfig(t, change)), re);
  });
}

test('runs/.gitignore without the * line', () => {
  expectProblem(problemsFor((t) => writeFileSync(join(t.agent, 'runs/.gitignore'), '!.gitignore\n!sample.jsonl\n')), /runs\/\.gitignore: must contain the line \*/);
});

test('runs/sample.jsonl problems', () => {
  const write = (t: { agent: string }, line: Obj) => writeFileSync(join(t.agent, 'runs/sample.jsonl'), JSON.stringify(line) + '\n');
  const { cost_usd: _drop, ...noCost } = SAMPLE_LINE;
  expectProblem(problemsFor((t) => write(t, noCost)), /sample\.jsonl: line 1: cost_usd/);
  expectProblem(problemsFor((t) => write(t, { ...SAMPLE_LINE, turns: -1 })), /sample\.jsonl: line 1: turns/);
  expectProblem(problemsFor((t) => write(t, { ...SAMPLE_LINE, agent: 'other-agent' })), /sample\.jsonl: line 1: agent must be "sample-agent"/);
});

test('evals/cases.jsonl problems', () => {
  const line = (id: string) => JSON.stringify({ id, expect: { outcome: 'pass' } });
  const write = (t: { agent: string }, text: string) => writeFileSync(join(t.agent, 'evals/cases.jsonl'), text);
  expectProblem(problemsFor((t) => write(t, `${line('x')}\n${line('x')}\n`)), /duplicate id "x"/);
  expectProblem(problemsFor((t) => write(t, JSON.stringify({ id: 'x' }) + '\n')), /cases\.jsonl: line 1 needs/);
  expectProblem(problemsFor((t) => write(t, '\n')), /cases\.jsonl: needs at least one case/);
});

test('evals/grade.ts disagreeing with the fixtures', () => {
  const problems = problemsFor((t) => writeFileSync(join(t.agent, 'evals/grade.ts'), "console.error('WRONG case-x');\nprocess.exit(1);\n"));
  expectProblem(problems, /grade\.ts.*[\s\S]*WRONG case-x/);
  expectProblem(problemsFor((t) => rmSync(join(t.agent, 'evals/grade.ts'))), /evals\/grade\.ts: missing/);
});

test('SDK pin', () => {
  const pin = (t: { agent: string }, v: string) =>
    writeJson(join(t.agent, 'package.json'), { name: 'sample-agent', dependencies: { '@anthropic-ai/claude-agent-sdk': v } });
  expectProblem(problemsFor((t) => pin(t, '^0.3.330')), /package\.json: dependencies/);
  expectProblem(problemsFor((t) => writeJson(join(t.agent, 'package-lock.json'), { packages: { 'node_modules/@anthropic-ai/claude-agent-sdk': { version: '0.3.331' } } })), /package-lock\.json/);
  expectProblem(problemsFor((t) => rmSync(join(t.agent, 'package.json'))), /package\.json: missing/);
});

test('runner may not bypass permissions', () => {
  expectProblem(problemsFor((t) => writeFileSync(join(t.agent, 'src/main.ts'), "const o = { permissionMode: 'bypassPermissions' };\n")), /src\/main\.ts: must not use bypassPermissions/);
});

test('secrets: key-looking text and .env files', () => {
  const fake = 'sk-' + 'ant-' + 'x'.repeat(24);
  const problems = problemsFor((t) => writeFileSync(join(t.agent, 'notes.txt'), `key ${fake}\n`));
  expectProblem(problems, /^sample-agent\/notes\.txt: looks like it holds an API key/);
  assert.ok(!problems.some((p) => p.includes(fake)), 'a problem leaked the key');
  expectProblem(problemsFor((t) => writeFileSync(join(t.agent, '.env'), 'A=1\n')), /^sample-agent\/\.env:/);
});

test('a fresh copy of the template has every conventions file but is not yet an agent', () => {
  const t = build();
  try {
    cpSync(TEMPLATE, join(t.root, 'second-agent'), { recursive: true });
    const second = checkRoot(t.root).filter((p) => p.startsWith('second-agent/'));
    expectProblem(second, new RegExp(`still contains ${PLACEHOLDER}`));
    expectProblem(second, /name must equal the folder name/);
    const missingConvention = second.filter((p) => REQUIRED_FILES.some((f) => p.startsWith(`second-agent/${f}: missing`)));
    assert.deepEqual(missingConvention, []);
  } finally {
    rmSync(t.root, { recursive: true, force: true });
  }
});

test('validateRunLogLine', () => {
  assert.equal(validateRunLogLine(SAMPLE_LINE), null);
  assert.equal(validateRunLogLine({ ...SAMPLE_LINE, extra: 1 }), null);
  assert.equal(typeof validateRunLogLine(null), 'string');
  const bad: Obj[] = [
    { ts: 'not a date' }, { ts: 5 }, { agent: '' }, { model: 3 }, { turns: 1.5 }, { turns: -1 },
    { cost_usd: -0.1 }, { cost_usd: '1' }, { outcome: '' }, { detail: 1 }, { duration_ms: -1 }, { duration_ms: 'x' },
  ];
  for (const change of bad) assert.equal(typeof validateRunLogLine({ ...SAMPLE_LINE, ...change }), 'string', JSON.stringify(change));
  for (const key of Object.keys(SAMPLE_LINE)) {
    const copy: Obj = { ...SAMPLE_LINE };
    delete copy[key];
    assert.equal(typeof validateRunLogLine(copy), 'string', `missing ${key}`);
  }
});

test('the real projects/agents tree is clean', () => {
  assert.deepEqual(checkRoot(AGENTS_DIR), []);
});
