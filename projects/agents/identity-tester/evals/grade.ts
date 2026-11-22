import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { TOOL_NAMES } from '../src/commands.ts';
import type { ToolName, ToolRecord } from '../src/commands.ts';
import { gradeReport } from '../src/grade.ts';
import type { Records } from '../src/grade.ts';

export type CaseResult = { id: string; expected: string; got: string; detail: string; ok: boolean };

type Case = { id: string; records: Partial<Record<ToolName, string>>; report: unknown; expect: { outcome: string } };

export function gradeCases(evalsDir: string): { results: CaseResult[]; problems: string[] } {
  const results: CaseResult[] = [];
  const problems: string[] = [];
  const seen = new Set<string>();
  const lines = readFileSync(join(evalsDir, 'cases.jsonl'), 'utf8').split('\n').filter((l) => l.trim() !== '');

  for (const [i, text] of lines.entries()) {
    let c: Case;
    try {
      c = JSON.parse(text) as Case;
    } catch {
      problems.push(`cases.jsonl line ${i + 1} is not valid JSON`);
      continue;
    }
    if (seen.has(c.id)) problems.push(`duplicate case id ${c.id}`);
    seen.add(c.id);

    const records: Records = {};
    for (const tool of TOOL_NAMES) {
      const file = c.records?.[tool];
      if (file === undefined) continue;
      try {
        const rec = JSON.parse(readFileSync(join(evalsDir, file), 'utf8')) as ToolRecord;
        if (rec.tool !== tool) problems.push(`${c.id}: ${file} has tool ${rec.tool}, used as ${tool}`);
        records[tool] = rec;
      } catch (err) {
        problems.push(`${c.id}: cannot load fixture ${file} (${err instanceof Error ? err.message : String(err)})`);
      }
    }

    const { outcome, detail } = gradeReport(records, c.report);
    results.push({ id: c.id, expected: c.expect.outcome, got: outcome, detail, ok: outcome === c.expect.outcome });
  }

  const expects = results.map((r) => r.expected);
  if (!expects.includes('pass')) problems.push('no case expects pass');
  if (!expects.includes('fail')) problems.push('no case expects fail');
  if (!expects.some((e) => e !== 'pass' && e !== 'fail')) problems.push('no case expects a failed-run outcome');
  return { results, problems };
}

if (import.meta.main) {
  const { results, problems } = gradeCases(import.meta.dirname);
  for (const r of results) {
    console.log(r.ok ? `ok   ${r.id} -> ${r.got}` : `WRONG ${r.id}: expected ${r.expected}, got ${r.got} (${r.detail})`);
  }
  for (const p of problems) console.error(p);
  if (results.some((r) => !r.ok) || problems.length > 0) process.exitCode = 1;
  else console.log(`${results.length} cases ok`);
}
