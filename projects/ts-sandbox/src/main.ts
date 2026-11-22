import type { AddressInfo } from "node:net";
import { createApp } from "./server.ts";

function parsePort(raw: string | undefined): number | null {
  if (raw === undefined) return 3000;
  if (!/^\d+$/.test(raw)) return null;
  const port = Number(raw);
  return port <= 65535 ? port : null;
}

const port = parsePort(process.env["PORT"]);
if (port === null) {
  console.error("ts-sandbox: PORT must be an integer from 0 to 65535");
  process.exit(1);
}

const app = createApp();

app.listen(port, "127.0.0.1", () => {
  const { port: actual } = app.address() as AddressInfo;
  console.log(`ts-sandbox listening on http://127.0.0.1:${actual}`);
});

function shutdown(): void {
  app.close(() => process.exit(0));
  app.closeAllConnections();
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
