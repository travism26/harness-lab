import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SCENARIOS, gradeProposal, parseProposal } from '../src/grade.ts';
import { classifyRun, exitCodeFor } from '../src/outcome.ts';

test('the seven labels', () => {
  assert.deepEqual([...SCENARIOS], ['small', 'medium', 'big', 'huge', 'poc', 'bug', 'unattended']);
});

test('every allowed label with a reason is sized', () => {
  for (const scenario of SCENARIOS) assert.deepEqual(gradeProposal(true, { scenario, reason: 'because' }), { outcome: 'sized', detail: scenario });
});

test('a label off the list, a wrong-case label, an empty reason and a bad shape are invalid_output', () => {
  const bad: unknown[] = [
    { scenario: 'tiny', reason: 'r' },
    { scenario: 'Small', reason: 'r' },
    { scenario: 'ready-for-factory', reason: 'r' },
    { scenario: 'small', reason: '' },
    { scenario: 'small', reason: '   ' },
    { scenario: 'small' },
    { reason: 'r' },
    { scenario: 'small', reason: 'r', extra: 1 },
    { scenario: 1, reason: 'r' },
    { scenario: 'small', reason: 2 },
    'small', null, undefined, [], 7,
  ];
  for (const b of bad) assert.equal(gradeProposal(true, b).outcome, 'invalid_output', JSON.stringify(b));
});

test('a valid proposal without a real read of the issue is tool_not_run', () => {
  assert.equal(gradeProposal(false, { scenario: 'small', reason: 'r' }).outcome, 'tool_not_run');
});

test('parseProposal keeps the proposal', () => {
  assert.deepEqual(parseProposal({ scenario: 'bug', reason: 'r' }), { ok: true, proposal: { scenario: 'bug', reason: 'r' } });
});

const ok = { subtype: 'success', is_error: false, num_turns: 3, total_cost_usd: 0.001 };

test('classifyRun maps results to outcomes', () => {
  const base = { thrown: null, hookDenials: [], issueRead: true };
  assert.equal(classifyRun({ ...base, result: null }).outcome, 'error');
  assert.equal(classifyRun({ ...base, result: { ...ok, structured_output: { scenario: 'bug', reason: 'r' } } }).outcome, 'sized');
  assert.equal(classifyRun({ ...base, result: { ...ok, structured_output: { scenario: 'nope', reason: 'r' } } }).outcome, 'invalid_output');
  assert.equal(classifyRun({ ...base, result: { ...ok } }).outcome, 'invalid_output');
  assert.equal(classifyRun({ ...base, result: { ...ok, subtype: 'error_max_turns', is_error: true } }).outcome, 'max_turns');
  assert.equal(classifyRun({ ...base, result: { ...ok, subtype: 'error_max_budget_usd', is_error: true } }).outcome, 'max_budget');
  assert.equal(classifyRun({ ...base, result: { ...ok, subtype: 'error_max_structured_output_retries', is_error: true } }).outcome, 'invalid_output');
  assert.equal(classifyRun({ ...base, hookDenials: ['Bash'], result: { ...ok, structured_output: { scenario: 'bug', reason: 'r' } } }).outcome, 'denied_tool');
});

test('only sized exits 0', () => {
  assert.equal(exitCodeFor('sized'), 0);
  for (const o of ['invalid_output', 'tool_not_run', 'max_turns', 'max_budget', 'denied_tool', 'error'] as const) assert.equal(exitCodeFor(o), 2);
});
