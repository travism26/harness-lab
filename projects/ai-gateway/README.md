# ai-gateway

The Gateway is a loopback process that forwards a Call to the Upstream and appends one Call record, and holds no credential. Terms such as Call, Forwarded credential, Hint and Upstream mean what the [glossary](GLOSSARY.md) says. The decision is in [ADR 0001](docs/adr/0001-forward-only-on-loopback.md).

It does not forward a Call yet. Today it checks its flags, creates the private audit file and listens.

```bash
go run ./cmd/gateway --upstream https://api.anthropic.com/v1/messages
```

`--listen` defaults to `127.0.0.1:8791` and accepts only `127.0.0.1` or `::1`. `--upstream` is required. `--audit` defaults to `audit.jsonl` in the working directory.

## Test

```bash
./check
```
