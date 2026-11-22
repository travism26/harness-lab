import { TOOL_NAMES } from './commands.ts';
import type { ToolName, ToolRecord } from './commands.ts';
import { parseReport } from './report.ts';

export type Outcome =
  | 'pass'
  | 'fail'
  | 'max_turns'
  | 'max_budget'
  | 'denied_tool'
  | 'invalid_output'
  | 'tool_not_run'
  | 'tool_error'
  | 'report_mismatch'
  | 'error';
export type Records = Partial<Record<ToolName, ToolRecord>>;

const PART_OF: Record<ToolName, 'check' | 'tour'> = { run_check: 'check', run_tour: 'tour' };

export function gradeReport(records: Records, report: unknown): { outcome: Outcome; detail: string } {
  const parsed = parseReport(report);
  if (!parsed.ok) return { outcome: 'invalid_output', detail: parsed.problem };

  for (const tool of TOOL_NAMES) {
    if (!records[tool]) return { outcome: 'tool_not_run', detail: `${tool} was never run` };
  }
  for (const tool of TOOL_NAMES) {
    const rec = records[tool] as ToolRecord;
    if (rec.exit_code === null) {
      return { outcome: 'tool_error', detail: `${tool} has no exit code${rec.timed_out ? ' (timed out)' : ''}` };
    }
  }

  const passed = (tool: ToolName) => (records[tool] as ToolRecord).exit_code === 0;
  for (const tool of TOOL_NAMES) {
    const part = PART_OF[tool];
    const reported = parsed.report[part].status;
    if ((reported === 'pass') !== passed(tool)) {
      return {
        outcome: 'report_mismatch',
        detail: `${part} reported ${reported} but ${tool} exited ${(records[tool] as ToolRecord).exit_code}`,
      };
    }
  }
  const allPassed = TOOL_NAMES.every(passed);
  if ((parsed.report.overall === 'pass') !== allPassed) {
    return {
      outcome: 'report_mismatch',
      detail: `overall reported ${parsed.report.overall} but ${allPassed ? 'both commands exited 0' : 'a command failed'}`,
    };
  }

  if (allPassed) return { outcome: 'pass', detail: '' };
  const failing = TOOL_NAMES.filter((t) => !passed(t)).map((t) => `${t} exited ${(records[t] as ToolRecord).exit_code}`);
  return { outcome: 'fail', detail: failing.join('; ') };
}
