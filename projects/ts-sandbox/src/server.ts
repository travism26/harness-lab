import http from "node:http";
import { isStageStatus, tally } from "./tally.ts";
import type { StageStatus } from "./tally.ts";

const MAX_BODY_BYTES = 64 * 1024;

function send(
  res: http.ServerResponse,
  status: number,
  body: unknown,
  headers: http.OutgoingHttpHeaders = {},
): void {
  res.writeHead(status, { ...headers, "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

function parseStatuses(raw: string): StageStatus[] | string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return "body is not valid JSON";
  }
  const statuses =
    typeof parsed === "object" && parsed !== null
      ? (parsed as { statuses?: unknown }).statuses
      : undefined;
  if (!Array.isArray(statuses)) return "statuses must be an array";
  if (!statuses.every(isStageStatus)) {
    return "statuses must contain only pass, fail or not-run";
  }
  return statuses;
}

function handleTally(req: http.IncomingMessage, res: http.ServerResponse): void {
  const chunks: Buffer[] = [];
  let size = 0;

  req.on("data", (chunk: Buffer) => {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) {
      chunks.length = 0;
      return;
    }
    chunks.push(chunk);
  });
  // Replying only after the whole body is read keeps the client from seeing a reset before the 413.
  req.on("end", () => {
    if (size > MAX_BODY_BYTES) {
      send(res, 413, { error: "body larger than 64 KiB" });
      return;
    }
    const result = parseStatuses(Buffer.concat(chunks).toString("utf8"));
    if (typeof result === "string") {
      send(res, 400, { error: result });
    } else {
      send(res, 200, tally(result));
    }
  });
}

export function createApp(): http.Server {
  return http.createServer((req, res) => {
    const pathname = (req.url ?? "").split("?", 1)[0];
    if (pathname !== "/tally") {
      send(res, 404, { error: "not found" });
      req.resume();
      return;
    }
    if (req.method !== "POST") {
      send(res, 405, { error: "method not allowed" }, { allow: "POST" });
      req.resume();
      return;
    }
    handleTally(req, res);
  });
}
