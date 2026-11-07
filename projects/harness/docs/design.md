# Design brief

This records the decisions settled in the design grill of 2026-11-04 (four rounds). It is the starting point for post 0; it does not describe code that exists yet. Terms are defined in [GLOSSARY.md](../GLOSSARY.md) (with the lab-wide terms in the [root glossary](../../../GLOSSARY.md)) and the hardest-to-reverse choices are in [docs/adr/](adr/) and the lab-wide [root decision records](../../../docs/adr/).

## Series and audience

- **Reader:** working engineers who use Claude Code or Cursor daily but have never built a harness.
- **Tone:** modest and practical. Real code and what broke; no productivity figures or hype.
- **Success:** personal learning and a portfolio piece. An audience is a bonus.
- **License:** MIT.

## Episodes

| # | Topic |
|---|-------|
| 0 | Setting up the factory (the skeleton PR) |
| 1 | A minimal loop: one tool and a log |
| 2 | Secrets the model never sees: `.env`, then Vault behind the same interface |
| 3 | Auto-login on our own demo app with a login page |
| 4 | A daily cheapest-groceries job |
| 5 | Closing post on how the code was structured so AI could build and test it, using stand-in services such as a tiny Python auth server that always grants access |

Each episode gets its own short grill just before its tickets are written (the secret-swap design, the demo login app, the grocery price source).

## Posts and episode notes

When the factory finishes an episode it writes an episode notes file in this repository: what was built, what broke, key snippets and PR links. The post itself is written in the author's voice in [travism26/blog](https://github.com/travism26/blog), optionally from a first draft opened as a PR there.

## Harness

- Python, run with uv.
- A raw loop that calls the Claude API directly with its own tool loop, no Agent SDK. A later post may compare the two.
- Claude Haiku 5.5 by default, with one setting to switch to Sonnet 5.5 or Opus 5.5.
- Always calls Claude through OpenRouter, in Anthropic's request format via OpenRouter's Anthropic-compatible endpoint. The endpoint address is a setting.
- The OpenRouter key is the harness's only credential. It never uses a Claude subscription token, because Anthropic's February 2026 terms forbid subscription tokens in other tools.

## Factory

The factory is shared by every project in the lab, so it is no longer described here. See [the factory doc](../../../docs/factory/README.md) for the brakes, identity, switch rule and spend, and the lab-wide [decision records](../../../docs/adr/) ([0003](../../../docs/adr/0003-factory-claude-code-on-subscription-token-with-switch-rule.md), [0004](../../../docs/adr/0004-per-key-credit-limits-as-the-spend-stop.md), [0005](../../../docs/adr/0005-label-only-factory-start-and-no-secrets-for-forks.md), [0007](../../../docs/adr/0007-factory-scripts-from-the-default-branch-agents-without-github-token.md)).

## Location privacy

Area, postal code and chosen stores live only in an uncommitted local file, or in a repo secret if the job ever runs on GitHub. The repo holds only the fake store site and example settings.

## Setup guide

The post 0 PR includes a step-by-step guide for the owner-only setup: the GitHub App, two OpenRouter keys with limits, the subscription token, and repo secrets. It ends with a live check that the factory answers a test label.

## Next steps

1. This design brief, in the repo as one PR.
2. One worker builds post 0: project, tests, CI, factory workflows, setup guide and episode notes template.
3. After both merge and setup is done, episode 1 is written as tickets for the factory.

## Facts to verify in post 0

Checked against the providers' own pages on 2026-11-06. Quotes and links are in the [setup guide](../../../docs/factory/setup.md#what-was-verified-and-where).

- **OpenRouter's Anthropic-compatible endpoint: confirmed.** OpenRouter's own docs document an endpoint that accepts Anthropic's Messages format (`https://openrouter.ai/api/v1/messages`), and a Claude Code setup with base URL `https://openrouter.ai/api`. The secondhand source was [Morph](https://www.morphllm.com/openrouter-anthropic-skin).
- **Per-key credit limits: confirmed.** Each key can have its own credit limit in USD. Without a reset interval the limit is a lifetime cap. A key at its limit gets `403 Key limit exceeded`.
- **Subscription tokens in other tools: confirmed in substance, but not the date.** Anthropic's Claude Code legal page says subscription OAuth is for Claude Code and Anthropic's own apps, and that products, including those built on the Agent SDK, must use API keys. Anthropic's pages do not date the change, and they do not carry the sentence quoted by [The Register, 2026-02-20](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access). "February 2026" above comes from that press report.
- **Claude Code in CI on one's own repo with a subscription token: documented, but not explicitly allowed.** Anthropic's GitHub Actions page documents `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` for Actions runs, billed to the subscription. No Anthropic page says outright that personal CI use is allowed. The legal page says plan limits assume "ordinary, individual usage". The switch rule stands as written.
