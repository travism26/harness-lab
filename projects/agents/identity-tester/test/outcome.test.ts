import assert from 'node:assert/strict';
import { test } from 'node:test';
import { classifyRun, exitCodeFor } from '../src/outcome.ts';
import type { ResultLike } from '../src/outcome.ts';
import type { Outcome, Records } from '../src/grade.ts';

const okRecords: Records = {
  run_check: { tool: 'run_check', exit_code: 0, timed_out: false, output: '' },
  run_tour: { tool: 'run_tour', exit_code: 0, timed_out: false, output: '' },
};
const goodReport = {
  check: { status: 'pass', evidence: 'e' }, tour: { status: 'pass', evidence: 'e' }, overall: 'pass', summary: 's',
};
const result = (over: Partial<ResultLike> = {}): ResultLike => ({
  subtype: 'success', is_error: false, num_turns: 3, total_cost_usd: 0.01, structured_output: goodReport, ...over,
});
const classify = (r: ResultLike | null, over: { thrown?: string | null; hookDenials?: string[]; records?: Records } = {}) =>
  classifyRun({ result: r, thrown: over.thrown ?? null, hookDenials: over.hookDenials ?? [], records: over.records ?? okRecords });

test('no result is error, with the thrown message or a default', () => {
  assert.deepEqual(classify(null, { thrown: 'boom' }), { outcome: 'error', detail: 'boom' });
  assert.deepEqual(classify(null), { outcome: 'error', detail: 'no result message' });
});

test('hook denials and permission_denials are denied_tool, de-duplicated', () => {
  assert.deepEqual(classify(result(), { hookDenials: ['Bash', 'Bash'] }), { outcome: 'denied_tool', detail: 'denied: Bash' });
  assert.deepEqual(
    classify(result({ permission_denials: [{ tool_name: 'Write' }, { tool_name: 'Bash' }] }), { hookDenials: ['Bash'] }),
    { outcome: 'denied_tool', detail: 'denied: Bash, Write' },
  );
});

test('denied_tool wins over an error subtype', () => {
  assert.equal(classify(result({ subtype: 'error_max_turns' }), { hookDenials: ['Bash'] }).outcome, 'denied_tool');
});

test('error subtypes', () => {
  assert.deepEqual(classify(result({ subtype: 'error_max_turns' })), { outcome: 'max_turns', detail: 'error_max_turns' });
  assert.deepEqual(classify(result({ subtype: 'error_max_budget_usd' })), { outcome: 'max_budget', detail: 'error_max_budget_usd' });
  assert.deepEqual(classify(result({ subtype: 'error_max_structured_output_retries' })), {
    outcome: 'invalid_output', detail: 'error_max_structured_output_retries',
  });
  assert.deepEqual(classify(result({ subtype: 'error_during_execution' })), { outcome: 'error', detail: 'error_during_execution' });
});

test('success with is_error is error', () => {
  assert.deepEqual(classify(result({ is_error: true })), { outcome: 'error', detail: 'result is_error' });
});

test('missing structured_output is invalid_output', () => {
  const expected = { outcome: 'invalid_output', detail: 'no structured_output on the result' };
  assert.deepEqual(classify(result({ structured_output: undefined })), expected);
  assert.deepEqual(classify(result({ structured_output: null })), expected);
});

test('otherwise the report is graded', () => {
  assert.deepEqual(classify(result()), { outcome: 'pass', detail: '' });
  assert.equal(classify(result(), { records: {} }).outcome, 'tool_not_run');
});

test('exitCodeFor', () => {
  const all: Outcome[] = [
    'pass', 'fail', 'max_turns', 'max_budget', 'denied_tool', 'invalid_output', 'tool_not_run', 'tool_error',
    'report_mismatch', 'error',
  ];
  for (const o of all) assert.equal(exitCodeFor(o), o === 'pass' ? 0 : o === 'fail' ? 1 : 2, o);
});
