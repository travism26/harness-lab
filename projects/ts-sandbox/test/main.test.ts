import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { afterEach, describe, expect, it } from "vitest";

const projectDir = import.meta.dirname + "/..";
const children: ChildProcess[] = [];

function start(port: string): ChildProcess {
  const child = spawn(process.execPath, ["src/main.ts"], {
    cwd: projectDir,
    env: { ...process.env, PORT: port },
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  return child;
}

function exited(child: ChildProcess): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve({ code: child.exitCode, signal: child.signalCode });
  }
  return new Promise((resolve) => {
    child.once("close", (code, signal) => resolve({ code, signal }));
  });
}

function listeningUrl(child: ChildProcess): Promise<string> {
  return new Promise((resolve, reject) => {
    let out = "";
    const timer = setTimeout(
      () => reject(new Error(`no listening line within 10 s; stdout: ${out}`)),
      10_000,
    );
    child.stdout?.on("data", (chunk: Buffer) => {
      out += chunk.toString();
      const match = /listening on (http:\/\/127\.0\.0\.1:\d+)\n/.exec(out);
      if (match?.[1]) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
    child.once("exit", () => {
      clearTimeout(timer);
      reject(new Error(`exited before listening; stdout: ${out}`));
    });
  });
}

afterEach(() => {
  for (const child of children.splice(0)) child.kill("SIGKILL");
});

describe("main", () => {
  it("serves on an ephemeral port and exits on SIGTERM", async () => {
    const child = start("0");
    const url = await listeningUrl(child);

    const res = await fetch(`${url}/tally`, {
      method: "POST",
      body: '{"statuses": ["pass", "fail"]}',
    });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ passed: 1, total: 2 });

    child.kill("SIGTERM");
    expect(await exited(child)).toEqual({ code: 0, signal: null });
  });

  it("exits 1 for a bad PORT", async () => {
    const child = start("abc");
    let stderr = "";
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    expect((await exited(child)).code).toBe(1);
    expect(stderr).toContain("PORT");
  });
});
