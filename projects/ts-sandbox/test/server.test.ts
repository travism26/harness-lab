import http from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApp } from "../src/server.ts";

const app = createApp();
let base = "";

beforeAll(async () => {
  await new Promise<void>((resolve) => app.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${(app.address() as AddressInfo).port}`;
});

afterAll(async () => {
  app.closeAllConnections();
  await new Promise<void>((resolve) => app.close(() => resolve()));
});

function post(body: string, path = "/tally"): Promise<Response> {
  return fetch(base + path, { method: "POST", body });
}

describe("POST /tally", () => {
  it("returns the tally", async () => {
    const res = await post('{"statuses": ["pass", "fail", "not-run"]}');
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("application/json");
    expect(await res.json()).toEqual({ passed: 1, total: 3 });
  });

  it("ignores a query string", async () => {
    const res = await post('{"statuses": []}', "/tally?x=1");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ passed: 0, total: 0 });
  });

  it.each([
    ["invalid JSON", "{nope"],
    ["missing statuses", "{}"],
    ["statuses not an array", '{"statuses": "pass"}'],
    ["an unknown status", '{"statuses": ["pass", "skipped"]}'],
    ["a non-object body", "null"],
  ])("returns 400 for %s", async (_name, body) => {
    const res = await post(body);
    expect(res.status).toBe(400);
    expect(res.headers.get("content-type")).toBe("application/json");
    expect(await res.json()).toEqual({ error: expect.any(String) });
  });

  it("returns 413 for a body over 64 KiB", async () => {
    const res = await post("x".repeat(64 * 1024 + 1));
    expect(res.status).toBe(413);
    expect(res.headers.get("content-type")).toBe("application/json");
    expect(await res.json()).toEqual({ error: expect.any(String) });
  });

  it("returns 405 with an Allow header for other methods", async () => {
    const res = await fetch(`${base}/tally`);
    expect(res.status).toBe(405);
    expect(res.headers.get("allow")).toBe("POST");
    expect(res.headers.get("content-type")).toBe("application/json");
    expect(await res.json()).toEqual({ error: expect.any(String) });
  });
});

describe("other paths", () => {
  it("returns 404", async () => {
    const res = await fetch(`${base}/nope`);
    expect(res.status).toBe(404);
    expect(res.headers.get("content-type")).toBe("application/json");
    expect(await res.json()).toEqual({ error: expect.any(String) });
  });
});

describe("odd request targets", () => {
  function rawStatus(path: string): Promise<number> {
    const { port } = app.address() as AddressInfo;
    return new Promise((resolve, reject) => {
      const req = http.request({ host: "127.0.0.1", port, path }, (res) => {
        res.resume();
        resolve(res.statusCode ?? 0);
      });
      req.on("error", reject);
      req.end();
    });
  }

  it.each(["//", "/\\", "http://", "*"])("answers 404 for target %s and keeps serving", async (target) => {
    expect(await rawStatus(target)).toBe(404);
    const res = await post('{"statuses": ["pass"]}');
    expect(res.status).toBe(200);
  });
});
