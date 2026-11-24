# ai-gateway

The Gateway is a loopback process that forwards a Call to the Upstream and appends one Call record, and holds no credential. Terms such as Call, Forwarded credential, Hint and Upstream mean what the [glossary](GLOSSARY.md) says. The decision is in [ADR 0001](docs/adr/0001-forward-only-on-loopback.md).

It forwards `POST /v1/messages` (query string kept) to `--upstream` and appends one Call record per Call to the audit file. Every other method and path gets a local 404. A reply whose `Content-Type` is `text/event-stream` is flushed to the client on every read, and its Call record is appended after the stream ends, with the latest value of each token counter sent in the stream. Any other reply is copied to completion and then flushed.

```bash
go run ./cmd/gateway --upstream https://api.anthropic.com/v1/messages
```

`--listen` defaults to `127.0.0.1:8791` and accepts only `127.0.0.1` or `::1`. `--upstream` is required. `--audit` defaults to `audit.jsonl` in the working directory.

## Redact and report

The audit file holds raw bodies and stays private: do not paste it, attach it or open an issue with it. Two commands work on a copy. Neither calls a model or the network, and neither touches the running Gateway.

```bash
go run ./cmd/redact audit.jsonl redacted.jsonl
go run ./cmd/report audit.jsonl
```

`redact <input> <output>` writes a copy of the Call-record file in which every string value, in `request_body` and `response_body` and in every other field, has secret-shaped text replaced by a tag: `[REDACTED:anthropic-key]` (`sk-ant-…`, `ANTHROPIC_API_KEY=…`), `[REDACTED:oauth]` (`sk-ant-oat…` and `sk-ant-ort…` tokens, `access_token`, `refresh_token` and `id_token` values, JWT-shaped values), `[REDACTED:bearer]` (`Bearer <token>`), `[REDACTED:pem]` (a PEM private key block) and `[REDACTED:header]` (an `Authorization` or `x-api-key` value). A body is stored as a plain string, so the patterns run over its text, JSON or not. Record order is kept and every line stays valid JSON; non-string values are untouched, and keys come out sorted. It refuses to write over its input, prints one count per kind to stderr and never prints matched text. Redaction is pattern-based and best-effort, so read a redacted copy before sharing it. The redacted copy is what may be discussed or attached.

`report <input>` prints the number of records, the records of each `x-claude-code-session-id` (records without one are listed as `(no session id)`), the sum of each `usage` token counter, p50 and p95 of `latency_ms`, and a cost estimate. Its record type has no body field, so it cannot print a body. Percentiles use the nearest-rank method: the value at rank `ceil(p/100 × n)` of the sorted latencies.

The cost is an estimate from Anthropic's published list prices, not an invoice. The prices in `internal/report/prices.go` were read on 2026-11-22 from <https://platform.claude.com/docs/en/about-claude/pricing>. A record is priced by its `model`, matched to a model name on that page (`claude-sonnet-4-5-20250929` is Claude Sonnet 4.5); a model with no match is shown as "no list price" and is left out of the total. Cache creation tokens are priced as 5-minute cache writes, since a record does not say which duration was used. Batch, fast mode, data residency and negotiated prices are not modelled.

A `--redact-audit` flag on the Gateway's write path could be a follow-up; today the Gateway always writes the raw record.

## Test

```bash
./check
```
