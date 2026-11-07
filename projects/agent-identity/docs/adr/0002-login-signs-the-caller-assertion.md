# The Login signs the Caller assertion; the Warden doesn't take the Agent's word for who is asking

Every Lookup carries two tokens: the Agent's JWT-SVID in `Authorization: Bearer`, and a Caller assertion signed by the Login in a `Caller-Assertion` header. The assertion is an ES256 JWT with `iss` (the Login), `sub` (the Caller), `aud` (the Warden's SPIFFE ID), `iat`, `exp` (5 minutes) and `may_act: {sub: <Agent SPIFFE ID>}` (RFC 8693). The Warden accepts the pair only if both verify and `may_act.sub` equals the JWT-SVID's `sub`. Being on the Agent allowlist lets an Agent ask at all; it never lets the Agent say who the Caller is.

- The Project exists so the Warden decides only on what it can check. If the Warden trusted its allowlisted Agent to name the Caller, the one fact every Lookup check depends on would be taken on faith, and a compromised Agent could ask as anyone.
- The Caller can't go inside the JWT-SVID: the Workload API request takes only `audience` and `spiffe_id`, and spiffecli signs it, not us. So the Caller has to travel next to it, which is also how OAuth Transaction Tokens work: their token goes in its own header, alongside the workload credential, never in place of it.
- `may_act` binds the assertion to one Agent, so another allowlisted Agent that steals it gets nothing. It's the RFC 8693 claim for "this party may act for `sub`", chosen over OIDC's `azp` for its standard meaning.

## Considered options

- **Trusted forwarding:** the Agent sends a Caller field and the Warden believes it because of the JWT-SVID. Cheapest, and WIMSE allows it when the trust is explicit, but a compromised Agent can name any Caller.
- **One token from the Login, no JWT-SVID:** the Warden would learn who the Agent is only from the Login's word, the Agent's SPIFFE identity would do nothing, and the one token would be a bearer credential for both facts.
- **Token exchange (RFC 8693):** a token service turns the JWT-SVID and the Login's token into one token with `sub` and `act`. It's the textbook single-token answer, but it needs a third service and another hop.
- **OAuth Transaction Tokens:** standards-track and the same shape as this decision, but they need a token service too, and SPIFFE support for them is still only on its roadmap.

## Consequences

- The Login is a tiny token issuer. In the demo it holds an in-process key made at startup; the tests sign their own assertions. The Warden is given that one public key at startup: no JWKS fetching, `kid` ignored, ES256 only.
- The Warden checks the assertion with go-jose's `jwt` package (already a dependency through go-spiffe) using an injected clock and a 1-minute leeway, so expiry tests don't sleep. go-spiffe can't inject a clock for the JWT-SVID.
- Every Caller-assertion failure returns 401 with the same body as a JWT-SVID failure, never a Denial: missing, malformed, expired, a bad signature, a `may_act` mismatch, or a `sub` not in the Seed data. The reason goes to the audit log only.
- The assertion names only the Caller. The Warden reads the Caller's Tenant from Seed data.
- The Agent decodes the assertion's `sub` without verifying it, only to resolve `self` and fill in Reply text. It never uses it to decide anything.
