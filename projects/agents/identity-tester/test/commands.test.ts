import assert from 'node:assert/strict';
import { test } from 'node:test';
import { COMMANDS, OUTPUT_CAP, TARGET_DIR, childEnv, execRecorded } from '../src/commands.ts';

test('COMMANDS are exactly the two fixed commands', () => {
  assert.deepEqual(Object.keys(COMMANDS).sort(), ['run_check', 'run_tour']);
  assert.deepEqual(COMMANDS.run_check.argv, ['./check']);
  assert.deepEqual(COMMANDS.run_tour.argv, ['go', 'run', './cmd/demo', 'tour']);
  assert.ok(TARGET_DIR.endsWith('projects/agent-identity'));
});

test('childEnv drops secret-shaped names and keeps the rest', () => {
  const out = childEnv({
    ANTHROPIC_API_KEY: 'a', CLAUDE_CODE_X: 'b', GITHUB_TOKEN: 'c', MY_SECRET: 'd', db_password: 'e',
    PATH: '/bin', HOME: '/h', GOFLAGS: '-v', GONE: undefined,
  });
  assert.deepEqual(out, { PATH: '/bin', HOME: '/h', GOFLAGS: '-v' });
});

const node = (script: string, timeoutMs?: number, env?: NodeJS.ProcessEnv) =>
  execRecorded('run_check', [process.execPath, '-e', script], { cwd: process.cwd(), timeoutMs, env });

test('exit 0 captures stdout and stderr', async () => {
  const r = await node("console.log('out'); console.error('err')");
  assert.equal(r.exit_code, 0);
  assert.equal(r.timed_out, false);
  assert.match(r.output, /out/);
  assert.match(r.output, /err/);
});

test('non-zero exit is recorded', async () => {
  assert.equal((await node('process.exit(3)')).exit_code, 3);
});

test('long output keeps the tail', async () => {
  const r = await node(`process.stdout.write('a'.repeat(${OUTPUT_CAP * 3}) + 'THE-END')`);
  assert.equal(r.output.length, OUTPUT_CAP);
  assert.ok(r.output.endsWith('THE-END'));
});

test('timeout kills the child', async () => {
  const r = await node('setTimeout(() => {}, 30000)', 200);
  assert.equal(r.timed_out, true);
  assert.equal(r.exit_code, null);
});

test('a missing binary gives a null exit code', async () => {
  const r = await execRecorded('run_tour', ['/no/such/binary-xyz'], { cwd: process.cwd() });
  assert.equal(r.exit_code, null);
  assert.equal(r.timed_out, false);
  assert.match(r.output, /ENOENT/);
});

test('the child does not see the API key', async () => {
  const r = await node('console.log(String(process.env.ANTHROPIC_API_KEY))', undefined, {
    ANTHROPIC_API_KEY: 'sk-secret-value', PATH: process.env.PATH,
  });
  assert.equal(r.output.trim(), 'undefined');
});
