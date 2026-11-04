# OpenRouter as the only provider, its key the only credential

The harness always calls Claude through OpenRouter, in Anthropic's request format, with the endpoint address as a setting. The OpenRouter key is the harness's only credential; it never uses a Claude subscription token, which Anthropic's February 2026 terms forbid in other tools. Calling Anthropic directly would be simpler, but OpenRouter gives per-key credit limits (see [0004](0004-per-key-credit-limits-as-the-spend-stop.md)) and keeps the one-credential rule easy to hold.
