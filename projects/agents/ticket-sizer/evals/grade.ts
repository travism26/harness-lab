import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { readFixture } from '../src/fixtures.ts';
import { SCENARIOS, gradeProposal, parseProposal } from '../src/grade.ts';

export type CaseResult = { id: string; expected: string; got: string; detail: string; ok: boolean };

type Expect = { outcome: string; scenario?: string; reason?: string };
type Case = { id: string; fixture: string; source: string; proposal: unknown; expect: Expect };

// Grades each recorded proposal with the same code the runner uses. No model is called: the
// proposals are hand-written stand-ins for what a correct (or a faulty) run would return.
export function gradeCases(evalsDir: string): { results: CaseResult[]; problems: string[] } {
  const results: CaseResult[] = [];
  const problems: string[] = [];
  const seen = new Set<string>();
  const used = new Set<string>();
  const fixturesDir = join(evalsDir, 'fixtures');
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
    if (typeof c.source !== 'string' || c.source.trim() === '') problems.push(`${c.id}: source must say where the fixture text came from`);

    used.add(c.fixture);
    const fixture = readFixture(c.fixture, fixturesDir);
    if (!fixture.ok) problems.push(`${c.id}: cannot load fixture ${String(c.fixture)} (${fixture.error})`);

    const { outcome, detail } = gradeProposal(fixture.ok, c.proposal);
    let ok = outcome === c.expect.outcome;
    let got: string = outcome;
    let why = detail;
    if (outcome === 'sized') {
      const p = parseProposal(c.proposal);
      if (!p.ok) throw new Error('unreachable: a sized outcome has a valid proposal');
      got = p.proposal.scenario;
      if (c.expect.scenario === undefined || !(SCENARIOS as readonly string[]).includes(c.expect.scenario)) {
        problems.push(`${c.id}: expect.scenario must be one of ${SCENARIOS.join(', ')}`);
      }
      if (c.expect.scenario !== got) ok = false;
      if (c.expect.reason === 'required' && p.proposal.reason.trim() === '') {
        ok = false;
        why = 'reason is empty';
      }
    }
    results.push({ id: c.id, expected: c.expect.scenario ?? c.expect.outcome, got, detail: why, ok });
  }

  const sizedLabels = lines.flatMap((l) => {
    try {
      const c = JSON.parse(l) as Case;
      return c.expect.outcome === 'sized' && c.expect.scenario !== undefined ? [c.expect.scenario] : [];
    } catch {
      return [];
    }
  });
  for (const must of ['small', 'huge']) if (!sizedLabels.includes(must)) problems.push(`no case expects ${must}`);
  if (sizedLabels.every((s) => s === 'medium')) problems.push('every sized case expects medium');
  if (!results.some((r) => r.expected === 'invalid_output')) problems.push('no case expects invalid_output');

  for (const f of readdirSync(fixturesDir)) {
    if (f.endsWith('.md') && !used.has(f.slice(0, -3))) problems.push(`fixture ${f} is used by no case`);
  }
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
