import { join } from 'node:path';
import type { AnyZodRawShape, createSdkMcpServer, query, tool } from '@anthropic-ai/claude-agent-sdk';
import { STRUCTURED_OUTPUT_TOOL, buildOptions, loadConfig, loadPrompt } from './config.ts';
import { FIXTURES_DIR, readFixture } from './fixtures.ts';
import type { FixtureResult } from './fixtures.ts';
import { PROPOSAL_SCHEMA, parseProposal } from './grade.ts';
import type { Outcome, Proposal } from './grade.ts';
import { classifyRun } from './outcome.ts';
import type { ResultLike } from './outcome.ts';
import { appendRunLog, redact } from './runlog.ts';
import type { RunLogLine } from './runlog.ts';

export type Sdk = { query: typeof query; tool: typeof tool; createSdkMcpServer: typeof createSdkMcpServer };

export const SERVER_NAME = 'issues';
export const TOOL_NAME = 'read_issue';
export const FULL_TOOL_NAME = `mcp__${SERVER_NAME}__${TOOL_NAME}`;
export const userPrompt = (fixture: string): string => `Size the issue in the fixture named "${fixture}" and return the proposal.`;

export type FinalOutput = {
  agent: string;
  model: string;
  fixture: string;
  outcome: Outcome;
  detail: string;
  issue_read: boolean;
  proposal: Proposal | null;
  turns: number;
  cost_usd: number;
};

export async function runAgent(deps: {
  sdk: Sdk;
  agentDir: string;
  fixture: string;
  // The zod shape of the tool's one input, { name: string }. main.ts builds it, so tests need no zod.
  inputShape: AnyZodRawShape;
  readIssue?: (name: unknown) => FixtureResult;
  now?: () => Date;
  secrets?: readonly string[];
}): Promise<{ line: RunLogLine; output: FinalOutput }> {
  const { sdk, agentDir, fixture } = deps;
  const readIssue = deps.readIssue ?? ((name: unknown) => readFixture(name, FIXTURES_DIR));
  const now = deps.now ?? (() => new Date());
  const secrets = deps.secrets ?? [];

  const config = loadConfig(agentDir);
  const prompt = loadPrompt(agentDir);
  if (config.allowedTools.length !== 1 || config.allowedTools[0] !== FULL_TOOL_NAME) {
    throw new Error(`projects/agents/ticket-sizer/agent.json allowedTools must be exactly ${FULL_TOOL_NAME}`);
  }

  // Code records which fixture the tool really returned. The model's claim to have read one counts for nothing.
  let issueRead = false;
  const hookDenials: string[] = [];

  const readTool = sdk.tool(
    TOOL_NAME,
    'Returns the text of one Lab issue from the local fixtures. Input: name, the bare fixture name the user gave you.',
    deps.inputShape,
    async (args) => {
      const name = (args as Record<string, unknown>).name;
      const r = readIssue(name);
      if (r.ok && name === fixture) issueRead = true;
      return { content: [{ type: 'text' as const, text: r.ok ? r.text : r.error }], isError: !r.ok };
    },
  );
  const server = sdk.createSdkMcpServer({ name: SERVER_NAME, version: '0.0.0', tools: [readTool], alwaysLoad: true });

  const allowed = new Set<string>([FULL_TOOL_NAME, STRUCTURED_OUTPUT_TOOL]);
  const options = buildOptions(config, prompt, {
    cwd: agentDir,
    mcpServers: { [SERVER_NAME]: server },
    hooks: {
      PreToolUse: [
        {
          hooks: [
            async (input) => {
              if (input.hook_event_name !== 'PreToolUse' || allowed.has(input.tool_name)) return {};
              hookDenials.push(input.tool_name);
              return {
                hookSpecificOutput: {
                  hookEventName: 'PreToolUse' as const,
                  permissionDecision: 'deny' as const,
                  permissionDecisionReason: `${input.tool_name} is not one of this agent's tools`,
                },
              };
            },
          ],
        },
      ],
    },
    outputSchema: PROPOSAL_SCHEMA,
  });

  let result: ResultLike | null = null;
  let thrown: string | null = null;
  let toolsSeen: string[] = [];
  const started = Date.now();
  try {
    for await (const message of sdk.query({ prompt: userPrompt(fixture), options })) {
      if (message.type === 'system' && message.subtype === 'init') toolsSeen = message.tools;
      else if (message.type === 'result') result = message;
    }
  } catch (err) {
    // A single-shot query() throws after yielding an error result, so keep any result already seen.
    thrown = err instanceof Error ? err.message : String(err);
  }
  const durationMs = Date.now() - started;

  const { outcome, detail } = classifyRun({ result, thrown, hookDenials, issueRead });
  const line: RunLogLine = {
    ts: now().toISOString(),
    agent: config.name,
    model: config.model,
    turns: result?.num_turns ?? 0,
    cost_usd: result?.total_cost_usd ?? 0,
    outcome,
    detail: redact(detail, secrets),
    duration_ms: durationMs,
    fixture,
    tools_seen: toolsSeen,
  };
  appendRunLog(join(agentDir, config.runLog), line);

  // The model's words are kept only for a sized run.
  let proposal: Proposal | null = null;
  if (outcome === 'sized') {
    const parsed = parseProposal((result as ResultLike | null)?.structured_output);
    if (parsed.ok) proposal = { scenario: parsed.proposal.scenario, reason: redact(parsed.proposal.reason, secrets) };
  }

  return {
    line,
    output: {
      agent: config.name,
      model: config.model,
      fixture,
      outcome,
      detail: line.detail,
      issue_read: issueRead,
      proposal,
      turns: line.turns,
      cost_usd: line.cost_usd,
    },
  };
}
