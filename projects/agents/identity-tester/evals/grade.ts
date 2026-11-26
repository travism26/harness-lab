import { readFileSync } from 'node:fs';
import { join } from 'node:path';

// Read against agent.json: the two tools the agent is allowed, plus the SDK's own report carrier.
const ALLOWED_TOOLS = ['mcp__identity__run_check', 'mcp__identity__run_tour', 'StructuredOutput'];
const REQUIRED_IDS = ['synthetic-clean', 'synthetic-job-change', 'synthetic-canary-absent', 'synthetic-canary-echoed'];
import { TOOL_NAMES } from '../src/commands.ts';
import type { ToolName, ToolRecord } from '../src/commands.ts';
import { gradeReport } from '../src/grade.ts';
import type { Records } from '../src/grade.ts';

export type CaseResult = { id: string; expected: string; got: string; detail: string; ok: boolean };

type Case = { id: string; records: Partial<Record<ToolName, string>>; tools?: unknown; report: unknown; expect: { outcome: string } };

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

    if (c.tools !== undefined) {
      if (!Array.isArray(c.tools)) problems.push(`${c.id}: tools must be an array`);
      else {
        for (const t of c.tools) {
          if (!ALLOWED_TOOLS.includes(t as string)) problems.push(`${c.id}: tool ${String(t)} is not one of ${ALLOWED_TOOLS.join(', ')}`);
        }
      }
    }
    for (const key of Object.keys(c.records ?? {})) {
      if (!(TOOL_NAMES as readonly string[]).includes(key)) problems.push(`${c.id}: records key ${key} is not run_check or run_tour`);
    }

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

  const byId = new Map(results.map((r) => [r.id, r.expected]));
  for (const id of REQUIRED_IDS) {
    const want = id === 'synthetic-canary-echoed' ? 'forbidden_text' : 'pass';
    if (!byId.has(id)) problems.push(`missing case ${id}`);
    else if (byId.get(id) !== want) problems.push(`case ${id} must expect ${want}`);
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
