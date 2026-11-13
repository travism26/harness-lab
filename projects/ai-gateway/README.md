# ai-gateway

The Gateway is a loopback process that forwards a Call to the Upstream and appends one Call record, and holds no credential. Terms such as Call, Forwarded credential, Hint and Upstream mean what the [glossary](GLOSSARY.md) says. The decision is in [ADR 0001](docs/adr/0001-forward-only-on-loopback.md).

It forwards `POST /v1/messages` (query string kept) to `--upstream` and appends one Call record per Call to the audit file. Every other method and path gets a local 404. A reply whose `Content-Type` is `text/event-stream` is flushed to the client on every read, and its Call record is appended after the stream ends, with the latest value of each token counter sent in the stream. Any other reply is copied to completion and then flushed.

```bash
go run ./cmd/gateway --upstream https://api.anthropic.com/v1/messages
```

`--listen` defaults to `127.0.0.1:8791` and accepts only `127.0.0.1` or `::1`. `--upstream` is required. `--audit` defaults to `audit.jsonl` in the working directory.

## Test

```bash
./check
```
