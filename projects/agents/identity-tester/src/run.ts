import { join } from 'node:path';
import type { createSdkMcpServer, query, tool } from '@anthropic-ai/claude-agent-sdk';
import { COMMANDS, TOOL_NAMES, runCommand } from './commands.ts';
import type { ToolName, ToolRecord } from './commands.ts';
import { STRUCTURED_OUTPUT_TOOL, buildOptions, loadConfig, loadPrompt } from './config.ts';
import type { Outcome, Records } from './grade.ts';
import { classifyRun } from './outcome.ts';
import type { ResultLike } from './outcome.ts';
import { REPORT_SCHEMA, parseReport } from './report.ts';
import type { Report, Status } from './report.ts';
import { appendRunLog, redact } from './runlog.ts';
import type { RunLogLine } from './runlog.ts';

export type Sdk = { query: typeof query; tool: typeof tool; createSdkMcpServer: typeof createSdkMcpServer };

export const SERVER_NAME = 'identity';
export const USER_PROMPT = 'Test agent-identity now and return the report.';

export type FinalOutput = {
  agent: string;
  model: string;
  outcome: Outcome;
  detail: string;
  commands: Record<ToolName, { exit_code: number | null; status: Status | null } | null>;
  report: Report | null;
  turns: number;
  cost_usd: number;
};

export async function runAgent(deps: {
  sdk: Sdk;
  agentDir: string;
  execute?: (tool: ToolName) => Promise<ToolRecord>;
  now?: () => Date;
  secrets?: readonly string[];
}): Promise<{ line: RunLogLine; output: FinalOutput }> {
  const { sdk, agentDir } = deps;
  const execute = deps.execute ?? runCommand;
  const now = deps.now ?? (() => new Date());
  const secrets = deps.secrets ?? [];

  const config = loadConfig(agentDir);
  const prompt = loadPrompt(agentDir);
  const expected = TOOL_NAMES.map((t) => `mcp__${SERVER_NAME}__${t}`);
  if (config.allowedTools.length !== expected.length || !expected.every((n) => config.allowedTools.includes(n))) {
    throw new Error(
      `projects/agents/identity-tester/agent.json allowedTools must be exactly ${expected.join(', ')}`,
    );
  }

  const records: Records = {};
  const hookDenials: string[] = [];

  const tools = TOOL_NAMES.map((name) =>
    sdk.tool(name, COMMANDS[name].description, {}, async () => {
      const record = await execute(name);
      records[name] = record;
      return {
        content: [
          { type: 'text' as const, text: JSON.stringify({ exit_code: record.exit_code, timed_out: record.timed_out, output: record.output }) },
        ],
        isError: record.exit_code === null,
      };
    }),
  );
  const server = sdk.createSdkMcpServer({ name: SERVER_NAME, version: '0.0.0', tools, alwaysLoad: true });

  const allowed = new Set<string>([...expected, STRUCTURED_OUTPUT_TOOL]);
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
    outputSchema: REPORT_SCHEMA,
  });

  let result: ResultLike | null = null;
  let thrown: string | null = null;
  let toolsSeen: string[] = [];
  const started = Date.now();
  try {
    for await (const message of sdk.query({ prompt: USER_PROMPT, options })) {
      if (message.type === 'system' && message.subtype === 'init') toolsSeen = message.tools;
      else if (message.type === 'result') result = message;
    }
  } catch (err) {
    // A single-shot query() throws after yielding an error result, so keep any result already seen.
    thrown = err instanceof Error ? err.message : String(err);
  }
  const durationMs = Date.now() - started;

  const { outcome, detail } = classifyRun({ result, thrown, hookDenials, records });
  const line: RunLogLine = {
    ts: now().toISOString(),
    agent: config.name,
    model: config.model,
    turns: result?.num_turns ?? 0,
    cost_usd: result?.total_cost_usd ?? 0,
    outcome,
    detail: redact(detail, secrets),
    duration_ms: durationMs,
    tools_seen: toolsSeen,
  };
  appendRunLog(join(agentDir, config.runLog), line);

  const commands = {} as FinalOutput['commands'];
  for (const name of TOOL_NAMES) {
    const rec = records[name];
    commands[name] = rec
      ? { exit_code: rec.exit_code, status: rec.exit_code === null ? null : rec.exit_code === 0 ? 'pass' : 'fail' }
      : null;
  }

  // The model's words are kept only when its report agreed with the recorded exit codes.
  let report: Report | null = null;
  if (outcome === 'pass' || outcome === 'fail') {
    const parsed = parseReport((result as ResultLike | null)?.structured_output);
    if (parsed.ok) {
      const r = parsed.report;
      report = {
        check: { status: r.check.status, evidence: redact(r.check.evidence, secrets) },
        tour: { status: r.tour.status, evidence: redact(r.tour.evidence, secrets) },
        overall: r.overall,
        summary: redact(r.summary, secrets),
      };
    }
  }

  return {
    line,
    output: {
      agent: config.name,
      model: config.model,
      outcome,
      detail: line.detail,
      commands,
      report,
      turns: line.turns,
      cost_usd: line.cost_usd,
    },
  };
}
