import { appendFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import type { Outcome } from './grade.ts';

export type RunLogLine = {
  ts: string;
  agent: string;
  model: string;
  turns: number;
  cost_usd: number;
  outcome: Outcome;
  detail: string;
  duration_ms: number;
  tools_seen: string[];
};

export function redact(text: string, secrets: readonly string[]): string {
  let out = text;
  // Short strings would redact ordinary words, so only long secrets count.
  for (const secret of secrets) if (secret.length >= 8) out = out.split(secret).join('[redacted]');
  return out;
}

export function appendRunLog(path: string, line: RunLogLine): void {
  mkdirSync(dirname(path), { recursive: true });
  appendFileSync(path, JSON.stringify(line) + '\n');
}
