import { lstatSync, readFileSync, realpathSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';

// The only files the agent can read: projects/agents/ticket-sizer/evals/fixtures/<name>.md
export const FIXTURES_DIR: string = resolve(import.meta.dirname, '../evals/fixtures');
export const MAX_FIXTURE_CHARS = 20_000;

// A bare name: no dot, no slash, no backslash, no drive letter. The code adds the .md itself, so
// "..", "a/b", "/etc/passwd" and "x.md" never reach the file system.
const NAME = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

export type FixtureResult = { ok: true; text: string } | { ok: false; error: string };

export function readFixture(name: unknown, dir: string = FIXTURES_DIR): FixtureResult {
  if (typeof name !== 'string' || !NAME.test(name)) {
    return { ok: false, error: 'name must be a bare fixture name: letters, digits, "-" and "_" only, no path and no extension' };
  }
  const path = join(dir, `${name}.md`);
  try {
    // A symlink is refused outright, and the resolved path must still sit inside the fixtures directory.
    if (!lstatSync(path).isFile()) return { ok: false, error: `no fixture named ${name}` };
    const real = realpathSync(path);
    if (!real.startsWith(realpathSync(dir) + sep)) return { ok: false, error: `no fixture named ${name}` };
    const text = readFileSync(real, 'utf8');
    if (text.length > MAX_FIXTURE_CHARS) return { ok: false, error: `fixture ${name} is larger than ${MAX_FIXTURE_CHARS} characters` };
    return { ok: true, text };
  } catch {
    return { ok: false, error: `no fixture named ${name}` };
  }
}
