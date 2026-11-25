# The Bench spends on a metered Anthropic API key, under its own cap

The factory's own Claude Code stays on the subscription token or an OpenRouter key, and Implement, Review and Rework stay on the switch rule (`docs/adr/0003-factory-claude-code-on-subscription-token-with-switch-rule.md`).

The Bench is a different caller. A Bench run spends on a metered Anthropic API key, so its dollars are that key's client-side estimates (the figure the harness reported, not a price table), recorded with `login` `anthropic-api` and `cost_note` `client-estimate`. The Bench enforces a monthly cap (UTC month, 100 USD by default) by reserving the cost of the next Bench run (3 USD: 2 for the build, 1 for Review) and refusing to start it when the remainder is lower. The stand-in harness never sees a GitHub token, the subscription token or an OpenRouter key.
