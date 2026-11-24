import { gradeProposal } from './grade.ts';
import type { Outcome } from './grade.ts';

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
  issueRead: boolean;
}): { outcome: Outcome; detail: string } {
  const { result, thrown, hookDenials, issueRead } = input;
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
  return gradeProposal(issueRead, result.structured_output);
}

// Only a sized run exits 0. Every other outcome is a failed run.
export function exitCodeFor(outcome: Outcome): 0 | 2 {
  return outcome === 'sized' ? 0 : 2;
}
