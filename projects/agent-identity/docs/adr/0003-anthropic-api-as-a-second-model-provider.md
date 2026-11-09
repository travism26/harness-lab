# The live Model runs on the Anthropic API first, with OpenRouter as the fallback

The live Model gets a second provider: Anthropic's own Messages API (`https://api.anthropic.com/v1/messages`), paid from the owner's Anthropic API credits. It becomes the default, and OpenRouter becomes the fallback. `--provider anthropic|openrouter` on `demo --live` and `cmd/eval` names one explicitly. Without the flag, the command uses Anthropic when its key is present and OpenRouter otherwise.

- The owner has about ten times more Anthropic API credit than OpenRouter credit ($200 against $20), and it covers the API and the Batch API. It is billed to the Console organization behind an Anthropic API key, not to the Claude subscription that the factory's `subscription` login uses.
- The change is small because OpenRouter's endpoint already speaks the Messages shape (`POST /api/v1/messages`). The same request body, strict `lookup_permission` tool, gate and repair retry work on both. Only four things differ: the URL, the auth headers (`x-api-key` plus `anthropic-version` instead of `Authorization: Bearer`), the model ids (`claude-haiku-5-5`, not `anthropic/claude-haiku-5.5`) and where the cost comes from.
- It's a direct call to the model maker, with no router in between. When a reply surprises us, that removes one layer from the question of who changed what.

## Considered options

- **OpenRouter only (the spec as written):** one provider and one key, but it spends the smaller balance while the larger one expires unused.
- **OpenRouter default, Anthropic opt-in:** keeps the spec's default, but the routine case would then need a flag.
- **Failing over to OpenRouter mid-run when an Anthropic call errors:** this would keep a run going. But one Eval report would then mix two providers, and the per-category accuracy would no longer describe one Model. The fallback is decided once, before the first request, and never per call.
- **Anthropic only:** drops OpenRouter's markup and one dependency, but `--model` would no longer take any OpenRouter id, and comparing against non-Anthropic models is the reason OpenRouter was chosen.
- **The official `anthropic-sdk-go` for the Anthropic provider:** typed and maintained by Anthropic, but it adds a dependency and a second code path for one strict call that plain `net/http` already makes for OpenRouter. Rejected while the call stays this small.
- **A Claude Code OAuth token instead of an API key:** already deferred to v2 in the spec, pending the terms of use. An API key is the supported way to bill the API.

## Consequences

- **Keys.** The live commands read `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY` from `projects/agent-identity/.env`, which is gitignored by the root `.gitignore`. Each process's own environment overrides that file. An explicit `--provider` whose key is missing exits non-zero before any request. With no flag and neither key present, the command does the same. The chosen provider is printed, and it is written to every Audit record and Eval report, so a fallback is never silent. `check` and CI use neither key: the stand-in Model serves both shapes.
- **The keys stay out of shell startup files.** If `ANTHROPIC_API_KEY` were exported from `~/.zshrc`, Claude Code would find it in every terminal and use it ahead of the subscription login, so ordinary Claude Code work would quietly move onto API billing. Reading the key from `.env` inside the Go command keeps it out of every shell.
- **Cost.** The Anthropic API reports tokens, not dollars. Its `usage` has no `cost`. The audit record's per-attempt `cost` for this provider is computed from `usage` and a price table kept in the code. Its rates in USD per million input/output tokens: Haiku 5.5 0.10/0.50, Sonnet 5.5 2/10, Opus 5.5 4/20. The record also carries `provider: "anthropic"`, so a computed cost is never mistaken for one the provider reported.
- **The Eval sweep** (Haiku 5.5 must pass; Sonnet 5.5 and Opus 5.5 report-only) can run on the Anthropic provider, and its reports name the provider.
- **Two request settings in the spec fail on the 5.5 models, whichever provider is used:**
  - `temperature: 0` is a 400 on the current API version (`2026-10-21`) for every model. On Sonnet 5.5 and Haiku 5.5, any non-default sampling value is a 400 on any version.
  - "No extended thinking" can't be honoured as written. Opus 5.5 rejects `thinking: {type: "disabled"}` at every effort level. Sonnet 5.5 rejects it too and takes `{type: "between_tools"}` instead. Haiku 5.5 accepts it only at effort `high` or below.

  Before M3 (the Model milestone), the spec should drop `temperature` and set `output_config.effort: "low"`, which keeps thinking short. It should also raise `max_tokens` from 256, because thinking tokens count against it and a cut-off reply would look like a fatal failure. The Eval's three runs per case then measure real run-to-run variation, not a fixed seed.
