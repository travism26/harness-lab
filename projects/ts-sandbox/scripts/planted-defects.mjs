import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const projectDir = path.resolve(import.meta.dirname, "..");
const verbose = process.argv.includes("--verbose");
const STAGE_NAMES = ["install", "typecheck", "lint", "test"];

const editJson = (file, edit) => (dir) => {
  const target = path.join(dir, file);
  const data = JSON.parse(fs.readFileSync(target, "utf8"));
  edit(data);
  fs.writeFileSync(target, JSON.stringify(data, null, 2) + "\n");
};
const appendTo = (file, text) => (dir) => fs.appendFileSync(path.join(dir, file), text);

const CASES = [
  { name: "none (baseline)", marker: null, apply: () => {}, expected: ["pass", "pass", "pass", "pass"], exit: 0 },
  {
    name: "install: package.json out of sync with the lockfile",
    marker: "EUSAGE",
    apply: editJson("package.json", (p) => {
      p.dependencies = { "left-pad": "1.3.0" };
    }),
    expected: ["fail", "not-run", "not-run", "not-run"],
    exit: 1,
  },
  {
    name: "install: Node outside engines",
    marker: "EBADENGINE",
    apply: editJson("package.json", (p) => {
      p.engines.node = "^18.0.0";
    }),
    expected: ["fail", "not-run", "not-run", "not-run"],
    exit: 1,
  },
  {
    name: "typecheck: type error",
    marker: "TS2322",
    apply: appendTo("src/tally.ts", '\nexport const plantedTypeError: number = "not a number";\n'),
    expected: ["pass", "fail", "pass", "pass"],
    exit: 1,
  },
  {
    name: "lint: ESLint violation",
    marker: "no-explicit-any",
    apply: appendTo("src/tally.ts", "\nexport const plantedLintDefect: any = 1;\n"),
    expected: ["pass", "pass", "fail", "pass"],
    exit: 1,
  },
  {
    name: "test: failing vitest test",
    marker: "planted.test.ts",
    apply: (dir) =>
      fs.writeFileSync(
        path.join(dir, "test/planted.test.ts"),
        'import { expect, it } from "vitest";\n\nit("fails on purpose", () => {\n  expect(1).toBe(2);\n});\n',
      ),
    expected: ["pass", "pass", "pass", "fail"],
    exit: 1,
  },
];

function sameList(a, b) {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

function invariantProblems(report) {
  const problems = [];
  if (report.project !== "ts-sandbox") problems.push("project");
  if (report.stack !== "typescript") problems.push("stack");
  const stages = Array.isArray(report.stages) ? report.stages : [];
  if (!sameList(stages.map((s) => s.name), STAGE_NAMES)) problems.push("stage names");
  for (const s of stages) {
    if (!sameList(Object.keys(s), ["name", "status", "duration_ms", "command"])) problems.push(`${s.name} keys`);
    if (!Number.isInteger(s.duration_ms) || s.duration_ms < 0) problems.push(`${s.name} duration_ms`);
    if (s.status === "not-run" && s.duration_ms !== 0) problems.push(`${s.name} not-run duration`);
  }
  if (report.total !== 4) problems.push("total");
  if (report.passed !== stages.filter((s) => s.status === "pass").length) problems.push("passed");
  return problems;
}

function runCase(c) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ts-sandbox-planted-"));
  try {
    fs.cpSync(projectDir, dir, {
      recursive: true,
      filter: (src) => path.basename(src) !== "node_modules",
    });
    c.apply(dir);
    const run = spawnSync("./check", ["--json"], {
      cwd: dir,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 16 * 1024 * 1024,
    });
    const stderr = run.stderr ?? "";
    if (verbose) process.stderr.write(stderr);
    const report = JSON.parse(run.stdout.trim());
    const statuses = report.stages.map((s) => s.status);
    const problems = invariantProblems(report);
    if (c.marker !== null && !stderr.includes(c.marker)) problems.push("marker not found");
    const ok = sameList(statuses, c.expected) && run.status === c.exit && problems.length === 0;
    return { name: c.name, marker: c.marker, statuses, passed: report.passed, total: report.total, exit: run.status, ok, problems };
  } catch (error) {
    return { name: c.name, marker: c.marker, statuses: ["?", "?", "?", "?"], passed: "?", total: "?", exit: "?", ok: false, problems: [String(error)] };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

const rows = CASES.map(runCase);

console.log("| Planted defect | install | typecheck | lint | test | passed/total | exit code | output contains | as expected |");
console.log("| --- | --- | --- | --- | --- | --- | --- | --- | --- |");
for (const r of rows) {
  console.log(`| ${r.name} | ${r.statuses.join(" | ")} | ${r.passed}/${r.total} | ${r.exit} | ${r.marker === null ? "-" : `\`${r.marker}\``} | ${r.ok ? "yes" : "NO"} |`);
}
for (const r of rows) {
  if (r.problems.length > 0) console.error(`${r.name}: ${r.problems.join("; ")}`);
}
const matched = rows.filter((r) => r.ok).length;
console.log(`planted-defects: ${matched}/${rows.length} cases as expected`);
process.exit(matched === rows.length ? 0 : 1);
