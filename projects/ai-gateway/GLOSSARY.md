# ai-gateway

A single-user forwarder on loopback for the owner's own Claude Code. Lab-wide terms (Project, Stand-in service and the rest) are in the [root glossary](../../GLOSSARY.md).

## Language

**Gateway**:
The loopback process in this Project that forwards a Call and appends one Call record, and holds no credential.
_Avoid_: Broker, product gateway

**Call**:
One client `POST /v1/messages` the Gateway accepts, including when the Upstream dial fails.
_Avoid_: Turn, Run

**Call record**:
The one JSON object appended for a Call, with who asked, both bodies, the status, token counts, and latency, and never a credential.
_Avoid_: Audit record, Run log

**Forwarded credential**:
The caller's `Authorization`, `x-api-key`, or cookie value, copied onto the Upstream request and nowhere else.
_Avoid_: Gateway credential, provider key

**Hint**:
An optional attribution fact Claude Code may attach, a fixed vocabulary or an id, never prompt text.
_Avoid_: Trace, span

**Upstream**:
The Anthropic Messages endpoint a Call is forwarded to; in tests, a Stand-in service.
_Avoid_: Provider, Broker
