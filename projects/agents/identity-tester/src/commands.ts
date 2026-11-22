import { spawn } from 'node:child_process';
import { resolve } from 'node:path';

export type ToolName = 'run_check' | 'run_tour';
export type ToolRecord = { tool: ToolName; exit_code: number | null; timed_out: boolean; output: string };

export const TOOL_NAMES: readonly ToolName[] = ['run_check', 'run_tour'];
export const TARGET_DIR: string = resolve(import.meta.dirname, '../../../agent-identity');

export const COMMANDS: Readonly<Record<ToolName, { argv: readonly string[]; description: string }>> = {
  run_check: {
    argv: ['./check'],
    description:
      "Runs agent-identity's offline check (gofmt, go vet, staticcheck, trustlint and the race-enabled tests). Takes no input; returns exit_code, timed_out and the end of the output.",
  },
  run_tour: {
    argv: ['go', 'run', './cmd/demo', 'tour'],
    description:
      "Runs agent-identity's offline demo tour. Takes no input; returns exit_code, timed_out and the end of the output.",
  },
};

export const OUTPUT_CAP = 6000;
export const TIMEOUT_MS = 10 * 60_000;

// The commands under test must never see a provider key, so secret-shaped names are dropped.
const SECRET_NAME = /KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL/i;

export function childEnv(env: NodeJS.ProcessEnv): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(env)) {
    if (value === undefined) continue;
    if (name.startsWith('ANTHROPIC_') || name.startsWith('CLAUDE_') || SECRET_NAME.test(name)) continue;
    out[name] = value;
  }
  return out;
}

export function execRecorded(
  tool: ToolName,
  argv: readonly string[],
  opts: { cwd: string; timeoutMs?: number; env?: NodeJS.ProcessEnv },
): Promise<ToolRecord> {
  return new Promise((resolvePromise) => {
    let output = '';
    let timedOut = false;
    let settled = false;
    const finish = (exitCode: number | null, extra: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (extra) output += (output && !output.endsWith('\n') ? '\n' : '') + extra;
      resolvePromise({ tool, exit_code: exitCode, timed_out: timedOut, output: output.slice(-OUTPUT_CAP) });
    };

    const child = spawn(argv[0] as string, argv.slice(1), {
      cwd: opts.cwd,
      env: childEnv(opts.env ?? process.env),
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, opts.timeoutMs ?? TIMEOUT_MS);

    const collect = (chunk: Buffer) => {
      output += chunk.toString('utf8');
      // Trim as we go so a chatty command cannot grow memory without bound.
      if (output.length > OUTPUT_CAP * 2) output = output.slice(-OUTPUT_CAP);
    };
    child.stdout.on('data', collect);
    child.stderr.on('data', collect);
    child.on('error', (err) => finish(null, err.message));
    child.on('close', (code, signal) => {
      if (timedOut) finish(null, '');
      else if (code === null) finish(null, `killed by signal ${signal}`);
      else finish(code, '');
    });
  });
}

export function runCommand(tool: ToolName): Promise<ToolRecord> {
  return execRecorded(tool, COMMANDS[tool].argv, { cwd: TARGET_DIR });
}
