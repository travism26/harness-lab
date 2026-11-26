import { gradeReport } from './grade.ts';
import type { Outcome, Records } from './grade.ts';

export type ResultLike = {
  subtype: string;
  is_error: boolean;
  num_turns: number;
  total_cost_usd: number;
  structured_output?: unknown;
  permission_denials?: readonly { tool_name: string }[];
};

export function classifyRun(input: {
  result: ResultLike | null;
  thrown: string | null;
  hookDenials: readonly string[];
  records: Records;
}): { outcome: Outcome; detail: string } {
  const { result, thrown, hookDenials, records } = input;
  if (!result) return { outcome: 'error', detail: thrown ?? 'no result message' };

  const denied = [...hookDenials, ...(result.permission_denials ?? []).map((d) => d.tool_name)];
  if (denied.length > 0) return { outcome: 'denied_tool', detail: `denied: ${[...new Set(denied)].join(', ')}` };

  if (result.subtype === 'error_max_turns') return { outcome: 'max_turns', detail: result.subtype };
  if (result.subtype === 'error_max_budget_usd') return { outcome: 'max_budget', detail: result.subtype };
  if (result.subtype === 'error_max_structured_output_retries') return { outcome: 'invalid_output', detail: result.subtype };
  if (result.subtype !== 'success') return { outcome: 'error', detail: result.subtype };
  if (result.is_error) return { outcome: 'error', detail: 'result is_error' };
  if (result.structured_output === undefined || result.structured_output === null) {
    return { outcome: 'invalid_output', detail: 'no structured_output on the result' };
  }
  return gradeReport(records, result.structured_output);
}

// forbidden_text is a failed run (2), like every outcome that is not pass or fail.
export function exitCodeFor(outcome: Outcome): 0 | 1 | 2 {
  if (outcome === 'pass') return 0;
  if (outcome === 'fail') return 1;
  return 2;
}
