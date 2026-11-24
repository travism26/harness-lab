export const SCENARIOS = ['small', 'medium', 'big', 'huge', 'poc', 'bug', 'unattended'] as const;
export type Scenario = (typeof SCENARIOS)[number];

export type Outcome =
  | 'sized'
  | 'invalid_output'
  | 'tool_not_run'
  | 'max_turns'
  | 'max_budget'
  | 'denied_tool'
  | 'error';

export type Proposal = { scenario: Scenario; reason: string };

export const PROPOSAL_SCHEMA: Record<string, unknown> = {
  type: 'object',
  properties: {
    scenario: { type: 'string', enum: [...SCENARIOS], description: 'The one workflow scenario the issue is' },
    reason: { type: 'string', description: 'One or two plain sentences naming what in the issue led to that label' },
  },
  required: ['scenario', 'reason'],
  additionalProperties: false,
};

type Parsed = { ok: true; proposal: Proposal } | { ok: false; problem: string };

export function parseProposal(value: unknown): Parsed {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return { ok: false, problem: 'proposal is not an object' };
  const v = value as Record<string, unknown>;
  for (const k of ['scenario', 'reason']) if (!(k in v)) return { ok: false, problem: `proposal.${k} is missing` };
  for (const k of Object.keys(v)) if (k !== 'scenario' && k !== 'reason') return { ok: false, problem: `proposal.${k} is not allowed` };
  if (typeof v.scenario !== 'string' || !(SCENARIOS as readonly string[]).includes(v.scenario)) {
    return { ok: false, problem: `scenario ${JSON.stringify(v.scenario)} is not one of ${SCENARIOS.join(', ')}` };
  }
  if (typeof v.reason !== 'string' || v.reason.trim() === '') return { ok: false, problem: 'reason must be a non-empty string' };
  return { ok: true, proposal: { scenario: v.scenario as Scenario, reason: v.reason } };
}

// The model's answer is a proposal. It stands only when it parses and the issue was really read.
export function gradeProposal(issueRead: boolean, proposal: unknown): { outcome: Outcome; detail: string } {
  const parsed = parseProposal(proposal);
  if (!parsed.ok) return { outcome: 'invalid_output', detail: parsed.problem };
  if (!issueRead) return { outcome: 'tool_not_run', detail: 'the issue fixture was never read' };
  return { outcome: 'sized', detail: parsed.proposal.scenario };
}
