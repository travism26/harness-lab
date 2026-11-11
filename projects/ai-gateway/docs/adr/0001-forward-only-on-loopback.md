# The Gateway forwards on loopback and holds no credential

The Gateway is a single-user loopback forwarder for the owner's own Claude Code. It is written in Go, speaks `net/http`, and accepts `POST /v1/messages` only. It stores both bodies in the Call record. It has no field and no code path for a credential: the Forwarded credential is copied onto the Upstream request and then dropped. The process reads no environment variable for its flags, a credential, or an HTTP proxy, loads no `.env`, and has no credential flag. It binds only to `127.0.0.1` or `::1`; any other listen address, and a start with no Upstream, exit before listen.

- Loopback and no credential of its own mean that reaching the Gateway gives no more than the caller already holds. Nothing it stores can be replayed as a key, because the Call record never has one.
- Reading no environment means a key or `HTTP_PROXY` in the shell cannot change where it binds or what it dials.
- Go is the language because the secret-log guard this repo already has is a Go analyzer, and the Project check beside it (`projects/agent-identity/check`) is the pattern to adapt. Python remains the harness's language.
- The Broker remains the only workload in the lab that holds a provider key (`projects/agent-identity/docs/adr/0004-the-provider-key-lives-only-in-the-broker.md`). This decision does not move that key.

## Considered options

- **Python, like the harness:** fits the rest of the harness, but the secret-type analyzer and its check would have to be rebuilt.
- **The Gateway holds the key and adds it:** callers would need no credential, but the Gateway would become a second holder of a provider key, against ADR 0004 of agent-identity.
- **Bind to any address behind a flag:** handy for other machines, but it would expose bodies and a forwarding path to the network. Rejected.
- **Read flags or a proxy from the environment:** convenient, but it lets ambient state redirect the Gateway. Rejected.

## Consequences

- Passing a different Upstream needs a flag; there is no default Upstream host.
- The Call record holds both bodies, so the audit file is private (mode `0600`) and is git-ignored.
- A caller with its own credential must send it on every Call.
