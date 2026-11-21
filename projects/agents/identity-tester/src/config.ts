import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Options } from '@anthropic-ai/claude-agent-sdk';

export type AgentConfig = {
  name: string;
  job: string;
  model: string;
  effort: 'low' | 'medium';
  maxTurns: number;
  maxBudgetUsd: number;
  settingSources: [];
  permissionMode: 'dontAsk';
  tools: string[];
  allowedTools: string[];
  disallowedTools: string[];
  runLog: string;
};

// The tool the SDK adds when outputFormat is set.
export const STRUCTURED_OUTPUT_TOOL = 'StructuredOutput';

const isStringArray = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === 'string');

export function loadConfig(agentDir: string): AgentConfig {
  const raw: unknown = JSON.parse(readFileSync(join(agentDir, 'agent.json'), 'utf8'));
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) throw new Error('agent.json must be an object');
  const c = raw as Record<string, unknown>;
  const str = (k: string): string => {
    const v = c[k];
    if (typeof v !== 'string' || v === '') throw new Error(`agent.json: ${k} must be a non-empty string`);
    return v;
  };
  const num = (k: string): number => {
    const v = c[k];
    if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) throw new Error(`agent.json: ${k} must be a positive number`);
    return v;
  };
  const strings = (k: string): string[] => {
    const v = c[k];
    if (!isStringArray(v)) throw new Error(`agent.json: ${k} must be an array of strings`);
    return v;
  };
  const effort = c.effort;
  if (effort !== 'low' && effort !== 'medium') throw new Error('agent.json: effort must be low or medium');
  if (!Array.isArray(c.settingSources) || c.settingSources.length !== 0) {
    throw new Error('agent.json: settingSources must be an empty array');
  }
  if (c.permissionMode !== 'dontAsk') throw new Error("agent.json: permissionMode must be 'dontAsk'");
  return {
    name: str('name'),
    job: str('job'),
    model: str('model'),
    effort,
    maxTurns: num('maxTurns'),
    maxBudgetUsd: num('maxBudgetUsd'),
    settingSources: [],
    permissionMode: 'dontAsk',
    tools: strings('tools'),
    allowedTools: strings('allowedTools'),
    disallowedTools: strings('disallowedTools'),
    runLog: str('runLog'),
  };
}

export function loadPrompt(agentDir: string): string {
  return readFileSync(join(agentDir, 'prompt.md'), 'utf8').trim();
}

// The only place query() options are assembled, so a new option cannot slip in elsewhere.
export function buildOptions(
  config: AgentConfig,
  prompt: string,
  parts: {
    cwd: string;
    mcpServers: NonNullable<Options['mcpServers']>;
    hooks: NonNullable<Options['hooks']>;
    outputSchema: Record<string, unknown>;
  },
): Options {
  return {
    model: config.model,
    systemPrompt: prompt,
    effort: config.effort,
    maxTurns: config.maxTurns,
    maxBudgetUsd: config.maxBudgetUsd,
    settingSources: config.settingSources,
    permissionMode: config.permissionMode,
    tools: config.tools,
    allowedTools: config.allowedTools,
    disallowedTools: config.disallowedTools,
    mcpServers: parts.mcpServers,
    hooks: parts.hooks,
    cwd: parts.cwd,
    outputFormat: { type: 'json_schema', schema: parts.outputSchema },
    strictMcpConfig: true,
    persistSession: false,
  };
}
