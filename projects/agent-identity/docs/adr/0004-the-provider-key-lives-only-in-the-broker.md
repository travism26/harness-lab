# The provider key lives only in the Broker

The Agent reaches the Model through a Broker, the only workload that holds a provider key. The Agent sends the Broker a JWT-SVID with the Broker's audience. The Broker checks it, looks up the Agent's SPIFFE ID in the Broker allowlist and holds the request to that workload's Pin. Only then does it add the key and forward the request. The Agent's process holds no static secret: it is identified on the Model hop the same way it is on the Warden hop, by what it is rather than by what it holds.

- A provider key in the Agent never expires and isn't tied to the Agent's identity. Anyone who copies it can spend the provider account from any machine, on any model, prompt and `max_tokens`. Behind the Broker, a leaked Agent can only ask for what its Pin allows.
- The Broker and the Warden have separate audiences, so a JWT-SVID minted for one fails at the other. A token stolen from one hop can't be replayed on the other.
- The Pin holds the model ids a workload may use with each provider, a `max_tokens` ceiling and a request-shape hash. The Broker fills in the model when the Pin allows only one, so the Agent no longer chooses a model or knows which provider served it until the response tells it. The request-shape hash covers every request field except `messages`, `model` and `max_tokens` (`system`, `tools`, `tool_choice`, `output_config` and any other top-level field), computed at start-up from the Model client's own request constants. That hash is what stops a compromised Agent swapping the system prompt: forcing the one tool would not, because the Model client sends `tool_choice: auto` (an Eval case may expect no Proposal), so the output is not limited to one tool call. The Agent can change only the question text.
- The Broker writes its own Audit record for every Model request. That gives an independent record of who used the key, and it's the authoritative one for tokens and cost.

## Considered options

- **The key stays in the Agent (before this ADR):** simplest, but it breaks the project's main claim, and nothing outside the Agent limits or records how the key is used.
- **A narrow `POST /propose {question}` endpoint, where the Broker owns the system prompt and tool schema:** tighter, but it moves Model-client logic into the Broker and reopens ADR 0001. The pass-through `POST /v1/messages` with a request-shape hash in the Pin gets most of the tightness and leaves ADR 0001 alone.
- **Each Pin names its own provider, and the Broker holds both keys:** lets workloads use different providers, but puts two keys in play for no benefit to the demo. The Broker chooses one provider at start-up, by the ADR 0003 rule.
- **The Eval keeps reading a key, as a named exception to trustlint R5:** less setup for a live Eval, but the rule would then have a hole. The Eval goes through the Broker under its own SPIFFE ID and Pin instead.
- **OAuth token exchange (RFC 8693), with the Agent swapping its JWT-SVID and the Caller assertion for a short-lived scoped token:** the planned follow-up, not this step. The Broker is a natural home for that token service.

## Consequences

- trustlint R5 (key isolation) fails `check` if any package outside the Broker module and the Broker command references the chosen provider key, calls the `.env` loader, or passes a provider key variable name to `os.Getenv` or `os.LookupEnv`. The Eval has no exception, and the Model client has no key mode.
- A live run needs a separate Broker process, started with the key, alongside spiffecli. A live Eval needs the same setup. "The Agent's process holds no key" is claimed only for that separate-process mode. The stand-in tour runs in one process with no real key anywhere.
- `demo --live --model` goes away: to try another model, change the Pin. `cmd/eval --model` stays, and the Broker checks it against the Eval's Pin.
- The Broker never passes a provider's error body on. An upstream failure becomes `502 upstream_error`, so a bad provider key can't be mistaken for a bad SVID.
- The Broker doesn't read the Caller assertion. Only the Warden reasons about the Caller, and the Correlation ID joins the Broker's records to the Agent's and the Warden's.
- A JWT-SVID names exactly one audience at both hops, and a request carries exactly one `Authorization` header, so a token minted for one hop can't pass at the other. Replaying a stolen token within its lifetime stays out of scope.
- Replay protection, rate limits, spend budgets, key rotation, streaming and mTLS are not covered. The Broker hop has the same bearer-token limits as the Warden hop.
