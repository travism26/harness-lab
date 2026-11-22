import { resolve } from 'node:path';
import { createSdkMcpServer, query, tool } from '@anthropic-ai/claude-agent-sdk';
import { z } from 'zod';
import { readFixture } from './fixtures.ts';
import { exitCodeFor } from './outcome.ts';
import { redact } from './runlog.ts';
import { runAgent } from './run.ts';

const key = process.env.ANTHROPIC_API_KEY ?? '';
const fixture = process.argv[2] ?? '';
if (key === '') {
  console.error(
    'ANTHROPIC_API_KEY is not set. This agent reads its key from the environment only; see projects/agents/ticket-sizer/README.md.',
  );
  process.exitCode = 2;
} else if (!readFixture(fixture).ok) {
  console.error('Pass the name of one fixture in projects/agents/ticket-sizer/evals/fixtures/, without the .md: npm start -- <fixture>');
  process.exitCode = 2;
} else {
  try {
    const { output } = await runAgent({
      sdk: { query, tool, createSdkMcpServer },
      agentDir: resolve(import.meta.dirname, '..'),
      fixture,
      inputShape: { name: z.string().describe('The bare fixture name, with no path and no extension') },
      secrets: [key],
    });
    console.log(JSON.stringify(output, null, 2));
    process.exitCode = exitCodeFor(output.outcome);
  } catch (err) {
    console.error(redact(err instanceof Error ? err.message : String(err), [key]));
    process.exitCode = 2;
  }
}
