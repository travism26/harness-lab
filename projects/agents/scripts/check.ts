import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

export const PINNED_MODEL = 'claude-haiku-5-5';
export const MAX_TURNS_CEILING = 30;
export const MAX_BUDGET_USD_CEILING = 1;
export const REQUIRED_DENIED = ['Bash', 'Write', 'Edit', 'NotebookEdit'] as const;
export const REQUIRED_FILES = [
  'README.md',
  'agent.json',
  'prompt.md',
  'evals/cases.jsonl',
  'runs/.gitignore',
  'runs/sample.jsonl',
] as const;
export const PLACEHOLDER = 'REPLACE-ME';

const SDK = '@anthropic-ai/claude-agent-sdk';
const MCP_TOOL = /^mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+$/;
const MAX_SCAN_BYTES = 1024 * 1024;

type Obj = Record<string, unknown>;

function isObj(v: unknown): v is Obj {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === 'string' && v.trim() !== '';
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'string');
}

function isNonNegNumber(v: unknown): boolean {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0;
}

export function validateRunLogLine(value: unknown): string | null {
  if (!isObj(value)) return 'must be a JSON object';
  if (typeof value.ts !== 'string' || Number.isNaN(Date.parse(value.ts))) return 'ts must be a date string';
  if (!isNonEmptyString(value.agent)) return 'agent must be a non-empty string';
  if (!isNonEmptyString(value.model)) return 'model must be a non-empty string';
  if (!Number.isInteger(value.turns) || (value.turns as number) < 0) return 'turns must be a non-negative integer';
  if (!isNonNegNumber(value.cost_usd)) return 'cost_usd must be a non-negative number';
  if (!isNonEmptyString(value.outcome)) return 'outcome must be a non-empty string';
  if (typeof value.detail !== 'string') return 'detail must be a string';
  if (!isNonNegNumber(value.duration_ms)) return 'duration_ms must be a non-negative number';
  return null;
}

function readText(path: string): string {
  return readFileSync(path, 'utf8');
}

function parseJson(path: string): { value: unknown } | { error: string } {
  try {
    return { value: JSON.parse(readText(path)) };
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}

function nonBlankLines(text: string): string[] {
  return text.split('\n').map((l) => l.trim()).filter((l) => l !== '');
}

function checkAgentJson(dir: string, label: string, agentMode: boolean, problems: string[]): Obj | null {
  const where = `${label}/agent.json`;
  const parsed = parseJson(join(dir, 'agent.json'));
  if ('error' in parsed) {
    problems.push(`${where}: not valid JSON (${parsed.error})`);
    return null;
  }
  const c = parsed.value;
  if (!isObj(c)) {
    problems.push(`${where}: must be a JSON object`);
    return null;
  }
  const bad = (msg: string) => problems.push(`${where}: ${msg}`);

  if (!isNonEmptyString(c.name)) bad('name must be a non-empty string');
  else if (agentMode && c.name !== label) bad(`name must equal the folder name "${label}", found "${c.name}"`);
  if (!isNonEmptyString(c.job)) bad('job must be a non-empty string');
  if (c.model !== PINNED_MODEL) bad(`model must be "${PINNED_MODEL}", found ${JSON.stringify(c.model)}`);
  if (c.effort !== 'low' && c.effort !== 'medium') bad(`effort must be "low" or "medium", found ${JSON.stringify(c.effort)}`);
  if (!Number.isInteger(c.maxTurns) || (c.maxTurns as number) < 1 || (c.maxTurns as number) > MAX_TURNS_CEILING) {
    bad(`maxTurns must be an integer from 1 to ${MAX_TURNS_CEILING}, found ${JSON.stringify(c.maxTurns)}`);
  }
  if (typeof c.maxBudgetUsd !== 'number' || !(c.maxBudgetUsd > 0) || c.maxBudgetUsd > MAX_BUDGET_USD_CEILING) {
    bad(`maxBudgetUsd must be a number above 0 and at most ${MAX_BUDGET_USD_CEILING}, found ${JSON.stringify(c.maxBudgetUsd)}`);
  }
  if (!Array.isArray(c.settingSources) || c.settingSources.length !== 0) bad('settingSources must be an empty array');
  if (c.permissionMode !== 'dontAsk') bad(`permissionMode must be "dontAsk", found ${JSON.stringify(c.permissionMode)}`);

  const denied: readonly string[] = REQUIRED_DENIED;
  const tools = isStringArray(c.tools) ? c.tools : null;
  const disallowed = isStringArray(c.disallowedTools) ? c.disallowedTools : null;
  const allowed = isStringArray(c.allowedTools) && c.allowedTools.length > 0 ? c.allowedTools : null;

  if (!tools) bad('tools must be an array of strings');
  else {
    const hit = tools.filter((t) => denied.includes(t));
    if (hit.length) bad(`tools must not list ${hit.join(', ')}`);
  }
  if (!disallowed) bad('disallowedTools must be an array of strings');
  else {
    const missing = REQUIRED_DENIED.filter((t) => !disallowed.includes(t));
    if (missing.length) bad(`disallowedTools must include ${missing.join(', ')}`);
  }
  if (!allowed) bad('allowedTools must be a non-empty array of strings');
  else {
    for (const t of allowed) {
      if (denied.includes(t)) bad(`allowedTools must not include ${t}`);
      else if (disallowed?.includes(t)) bad(`allowedTools entry ${t} is also in disallowedTools`);
      else if (!MCP_TOOL.test(t) && !tools?.includes(t)) bad(`allowedTools entry ${t} is neither an mcp__server__tool name nor listed in tools`);
    }
  }
  if (typeof c.runLog !== 'string' || !c.runLog.startsWith('runs/') || !c.runLog.endsWith('.jsonl')) {
    bad('runLog must start with "runs/" and end with ".jsonl"');
  }
  return c;
}

function checkCases(dir: string, label: string, problems: string[]): void {
  const where = `${label}/evals/cases.jsonl`;
  const lines = nonBlankLines(readText(join(dir, 'evals/cases.jsonl')));
  if (lines.length === 0) problems.push(`${where}: needs at least one case`);
  const seen = new Set<string>();
  lines.forEach((line, i) => {
    let v: unknown;
    try {
      v = JSON.parse(line);
    } catch {
      problems.push(`${where}: line ${i + 1} is not valid JSON`);
      return;
    }
    if (!isObj(v) || !isNonEmptyString(v.id) || !isObj(v.expect)) {
      problems.push(`${where}: line ${i + 1} needs a non-empty string "id" and an object "expect"`);
      return;
    }
    if (seen.has(v.id)) problems.push(`${where}: duplicate id "${v.id}"`);
    seen.add(v.id);
  });
}

function checkSample(dir: string, label: string, config: Obj | null, agentMode: boolean, problems: string[]): void {
  const where = `${label}/runs/sample.jsonl`;
  const lines = nonBlankLines(readText(join(dir, 'runs/sample.jsonl')));
  if (lines.length === 0) problems.push(`${where}: needs at least one run-log line`);
  lines.forEach((line, i) => {
    let v: unknown;
    try {
      v = JSON.parse(line);
    } catch {
      problems.push(`${where}: line ${i + 1} is not valid JSON`);
      return;
    }
    const err = validateRunLogLine(v);
    if (err) {
      problems.push(`${where}: line ${i + 1}: ${err}`);
      return;
    }
    if (agentMode && isObj(v)) {
      if (v.agent !== label) problems.push(`${where}: line ${i + 1}: agent must be "${label}", found "${String(v.agent)}"`);
      if (config && v.model !== config.model) problems.push(`${where}: line ${i + 1}: model must equal the model in ${label}/agent.json`);
    }
  });
}

function checkSdkPin(dir: string, label: string, problems: string[]): void {
  const pkg = parseJson(join(dir, 'package.json'));
  if (!existsSync(join(dir, 'package.json'))) {
    problems.push(`${label}/package.json: missing`);
    return;
  }
  let version: string | null = null;
  if ('error' in pkg) problems.push(`${label}/package.json: not valid JSON (${pkg.error})`);
  else {
    const deps = isObj(pkg.value) && isObj(pkg.value.dependencies) ? pkg.value.dependencies : {};
    const v = deps[SDK];
    if (typeof v === 'string' && /^\d+\.\d+\.\d+$/.test(v)) version = v;
    else problems.push(`${label}/package.json: dependencies["${SDK}"] must be an exact version like 1.2.3, found ${JSON.stringify(v)}`);
  }
  if (!existsSync(join(dir, 'package-lock.json'))) {
    problems.push(`${label}/package-lock.json: missing`);
    return;
  }
  const lock = parseJson(join(dir, 'package-lock.json'));
  if ('error' in lock) {
    problems.push(`${label}/package-lock.json: not valid JSON (${lock.error})`);
    return;
  }
  const packages = isObj(lock.value) && isObj(lock.value.packages) ? lock.value.packages : {};
  const entry = packages[`node_modules/${SDK}`];
  const locked = isObj(entry) ? entry.version : undefined;
  if (version !== null && locked !== version) {
    problems.push(`${label}/package-lock.json: ${SDK} is ${JSON.stringify(locked)} but package.json pins "${version}"`);
  }
}

function tsFilesUnder(dir: string): string[] {
  const out: string[] = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) out.push(...tsFilesUnder(p));
    else if (e.isFile() && e.name.endsWith('.ts')) out.push(p);
  }
  return out;
}

function checkRunner(dir: string, label: string, problems: string[]): void {
  if (!existsSync(join(dir, 'src/main.ts'))) problems.push(`${label}/src/main.ts: missing`);
  if (!existsSync(join(dir, 'src'))) return;
  for (const file of tsFilesUnder(join(dir, 'src'))) {
    const text = readText(file);
    for (const word of ['bypassPermissions', 'allowDangerouslySkipPermissions']) {
      if (text.includes(word)) problems.push(`${label}/${relative(dir, file).split(sep).join('/')}: must not use ${word}`);
    }
  }
}

function checkGrader(dir: string, label: string, problems: string[]): void {
  if (!existsSync(join(dir, 'evals/grade.ts'))) {
    problems.push(`${label}/evals/grade.ts: missing`);
    return;
  }
  const r = spawnSync(process.execPath, ['evals/grade.ts'], { cwd: dir, encoding: 'utf8', timeout: 60_000 });
  if (r.status !== 0) {
    const tail = `${r.stdout ?? ''}${r.stderr ?? ''}`.split('\n').filter((l) => l !== '').slice(-15).join('\n');
    problems.push(`${label}/evals/grade.ts: the eval grader disagrees with the recorded fixtures (exit ${r.status})${tail ? '\n' + tail : ''}`);
  }
}

function checkFolder(root: string, label: string, agentMode: boolean, problems: string[]): void {
  const dir = join(root, label);
  const have = new Set<string>();
  for (const f of REQUIRED_FILES) {
    if (existsSync(join(dir, f))) have.add(f);
    else problems.push(`${label}/${f}: missing`);
  }

  const config = have.has('agent.json') ? checkAgentJson(dir, label, agentMode, problems) : null;
  for (const f of ['prompt.md', 'README.md']) {
    if (have.has(f) && readText(join(dir, f)).trim() === '') problems.push(`${label}/${f}: empty`);
  }
  if (have.has('evals/cases.jsonl')) checkCases(dir, label, problems);
  if (have.has('runs/.gitignore')) {
    const lines = readText(join(dir, 'runs/.gitignore')).split('\n').map((l) => l.trim());
    for (const want of ['*', '!.gitignore', '!sample.jsonl']) {
      if (!lines.includes(want)) problems.push(`${label}/runs/.gitignore: must contain the line ${want}`);
    }
  }
  if (have.has('runs/sample.jsonl')) checkSample(dir, label, config, agentMode, problems);

  if (!agentMode) return;
  for (const f of ['README.md', 'agent.json', 'prompt.md', 'evals/cases.jsonl', 'runs/sample.jsonl']) {
    if (have.has(f) && readText(join(dir, f)).includes(PLACEHOLDER)) problems.push(`${label}/${f}: still contains ${PLACEHOLDER}`);
  }
  checkSdkPin(dir, label, problems);
  checkRunner(dir, label, problems);
  checkGrader(dir, label, problems);
}

const KEY_PATTERNS = [/sk-ant-[A-Za-z0-9_-]{10,}/, /ANTHROPIC_API_KEY\s*[=:]\s*["']?[A-Za-z0-9_-]{16,}/];

function checkSecrets(root: string, dir: string, problems: string[]): void {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    const rel = relative(root, p).split(sep).join('/');
    if (e.isDirectory()) {
      if (e.name !== 'node_modules') checkSecrets(root, p, problems);
      continue;
    }
    if (!e.isFile()) continue;
    if (e.name === '.env' || e.name.startsWith('.env.')) problems.push(`${rel}: env files must not be in the tree`);
    if (statSync(p).size > MAX_SCAN_BYTES) continue;
    const text = readText(p);
    if (KEY_PATTERNS.some((re) => re.test(text))) problems.push(`${rel}: looks like it holds an API key`);
  }
}

export function checkRoot(root: string): string[] {
  const problems: string[] = [];
  if (!existsSync(join(root, 'README.md'))) problems.push('README.md: missing');
  if (!existsSync(join(root, '_template'))) problems.push('_template: missing');

  const folders = readdirSync(root, { withFileTypes: true })
    .filter((e) => e.isDirectory() && e.name !== 'scripts' && e.name !== 'node_modules' && !e.name.startsWith('.'))
    .map((e) => e.name)
    .sort();
  for (const name of folders) checkFolder(root, name, name !== '_template', problems);
  checkSecrets(root, root, problems);
  return problems;
}

if (import.meta.main) {
  const root = join(import.meta.dirname, '..');
  const problems = checkRoot(root);
  if (problems.length > 0) {
    for (const p of problems) console.error(`projects/agents/${p}`);
    console.error(`agents check: ${problems.length} problem(s)`);
    process.exit(1);
  }
  const n = readdirSync(root, { withFileTypes: true }).filter(
    (e) => e.isDirectory() && e.name !== 'scripts' && e.name !== 'node_modules' && !e.name.startsWith('.') && e.name !== '_template',
  ).length;
  console.log(`agents check: ok (${n} agent folder(s) and the template)`);
}
