export type Status = 'pass' | 'fail';
export type Report = {
  check: { status: Status; evidence: string };
  tour: { status: Status; evidence: string };
  overall: Status;
  summary: string;
};

const statusSchema = (what: string) => ({ type: 'string', enum: ['pass', 'fail'], description: what });
const part = (what: string) => ({
  type: 'object',
  properties: {
    status: statusSchema(`pass only when ${what} exited 0, otherwise fail`),
    evidence: { type: 'string', description: 'One or two output lines that best show the result' },
  },
  required: ['status', 'evidence'],
  additionalProperties: false,
});

export const REPORT_SCHEMA: Record<string, unknown> = {
  type: 'object',
  properties: {
    check: part('run_check'),
    tour: part('run_tour'),
    overall: statusSchema('pass only when both commands passed, otherwise fail'),
    summary: { type: 'string', description: 'One or two plain sentences for someone deciding whether to look closer' },
  },
  required: ['check', 'tour', 'overall', 'summary'],
  additionalProperties: false,
};

type Parsed = { ok: true; report: Report } | { ok: false; problem: string };

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function exactKeys(v: Record<string, unknown>, keys: string[], where: string): string | null {
  for (const k of keys) if (!(k in v)) return `${where}.${k} is missing`;
  for (const k of Object.keys(v)) if (!keys.includes(k)) return `${where}.${k} is not allowed`;
  return null;
}

function isStatus(v: unknown): v is Status {
  return v === 'pass' || v === 'fail';
}

export function parseReport(value: unknown): Parsed {
  if (!isObject(value)) return { ok: false, problem: 'report is not an object' };
  const top = exactKeys(value, ['check', 'tour', 'overall', 'summary'], 'report');
  if (top) return { ok: false, problem: top };
  for (const name of ['check', 'tour'] as const) {
    const p = value[name];
    if (!isObject(p)) return { ok: false, problem: `report.${name} is not an object` };
    const bad = exactKeys(p, ['status', 'evidence'], `report.${name}`);
    if (bad) return { ok: false, problem: bad };
    if (!isStatus(p.status)) return { ok: false, problem: `report.${name}.status must be pass or fail` };
    if (typeof p.evidence !== 'string') return { ok: false, problem: `report.${name}.evidence must be a string` };
  }
  if (!isStatus(value.overall)) return { ok: false, problem: 'report.overall must be pass or fail' };
  if (typeof value.summary !== 'string') return { ok: false, problem: 'report.summary must be a string' };
  return { ok: true, report: value as unknown as Report };
}
