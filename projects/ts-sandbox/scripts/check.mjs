import { spawnSync } from "node:child_process";
import { performance } from "node:perf_hooks";
import path from "node:path";
import process from "node:process";

const projectDir = path.resolve(import.meta.dirname, "..");

const STAGES = [
  { name: "install", argv: ["npm", "ci"] },
  { name: "typecheck", argv: ["npx", "--no", "--", "tsc", "--noEmit"] },
  { name: "lint", argv: ["npx", "--no", "--", "eslint", "."] },
  { name: "test", argv: ["npx", "--no", "--", "vitest", "run"] },
];

const args = process.argv.slice(2);
if (args.length > 1 || (args.length === 1 && args[0] !== "--json")) {
  process.stderr.write("usage: check [--json]\n");
  process.exit(2);
}
const json = args[0] === "--json";

// In JSON mode stdout is reserved for the result object, so children write to stderr.
const stdio = json ? ["ignore", 2, 2] : "inherit";

const results = [];
let installFailed = false;
for (const { name, argv } of STAGES) {
  const command = argv.join(" ");
  if (installFailed) {
    results.push({ name, status: "not-run", duration_ms: 0, command });
    continue;
  }
  (json ? process.stderr : process.stdout).write(`==> ${name}: ${command}\n`);
  const start = performance.now();
  const run = spawnSync(argv[0], argv.slice(1), { cwd: projectDir, stdio });
  const duration_ms = Math.round(performance.now() - start);
  const status = run.error === undefined && run.status === 0 ? "pass" : "fail";
  if (run.error) process.stderr.write(`${name}: ${run.error.message}\n`);
  results.push({ name, status, duration_ms, command });
  if (name === "install" && status === "fail") installFailed = true;
}

const passed = results.filter((r) => r.status === "pass").length;
const total = results.length;

if (json) {
  process.stdout.write(
    JSON.stringify({ project: "ts-sandbox", stack: "typescript", stages: results, passed, total }) + "\n",
  );
} else {
  for (const r of results) {
    process.stdout.write(`${r.status}  ${r.name}  ${r.duration_ms} ms\n`);
  }
  process.stdout.write(`ts-sandbox: ${passed}/${total} stages passed\n`);
}
process.exit(passed === total ? 0 : 1);
