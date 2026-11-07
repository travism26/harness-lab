# Setup guide

The owner-only steps that wire the factory's credentials. Only the repository owner can do them,
because they create credentials and change settings. Do them in order, after the post 0 PR is
merged into `main`. It takes about half an hour. The guide ends with a live check that the factory
answers a test label.

You need:

- admin access to `travism26/harness-lab`;
- the factory's GitHub App, which is shared with claude-code-adw (Step 1 covers the case where it
  does not exist yet);
- a Claude subscription that includes Claude Code (Pro, Max or above);
- an OpenRouter account with about 20 USD of credit;
- `gh` and `uv` on your machine, in a clone of this repository.

## What you will end up with

| Name | Kind | What it holds |
|---|---|---|
| `FACTORY_APP_CLIENT_ID` | Variable | The shared App's Client ID (it starts with `Iv`) |
| `FACTORY_APP_KEY` | Secret | A private key of the App: the whole `.pem` file |
| `CLAUDE_CODE_OAUTH_TOKEN` | Secret | Your subscription token, from `claude setup-token` |
| `OPENROUTER_API_KEY` | Secret | The OpenRouter key for GitHub runs, limited to 10 USD |

The second OpenRouter key, for local runs and the daily groceries job, never goes on GitHub.

## Step 1. Give the shared App what this repo needs

The factory acts on GitHub as one GitHub App, the same one claude-code-adw uses. Its comments
and labels show as `<app-name>[bot]`. Events it causes start other workflows. Events caused by the
built-in `GITHUB_TOKEN` never do, and Review's `rework` label has to start Rework.

If the App does not exist yet, create it with Steps 1 and 2 of claude-code-adw's
[GitHub App setup](https://github.com/travism26/claude-code-adw/blob/main/docs/factory/github-app-setup.md),
then come back here.

1. Open the App's settings: your profile picture, **Settings**, **Developer settings**,
   **GitHub Apps**, then **Edit** next to the App.
2. Open **Permissions & events**. Under **Repository permissions** set:

   | Permission | Access | Why |
   |---|---|---|
   | Contents | Read and write | Push the factory's `factory/issue-<N>` branches |
   | Issues | Read and write | Read Tickets, comment on them, move labels |
   | Pull requests | Read and write | Open draft PRs, post the review, move labels |
   | Metadata | Read-only | Required by GitHub |

   Leave **Workflows** at **No access**. Without it, the factory cannot push changes to its own
   workflows.

   Contents: Read and write is wider than claude-code-adw's guide asked for. Permissions belong to
   the App, so this applies to its claude-code-adw installation too. GitHub asks you to approve the
   change on each installation before it takes effect.
3. Click **Save changes**.
4. In the left sidebar click **Install App**, then the gear next to your account. Under
   **Repository access**, keep **Only select repositories** and add `harness-lab`. Click **Save**.
   If GitHub shows a banner asking you to accept new permissions, accept them.
5. On the App's **General** page, copy the **Client ID** (not the App ID).
6. Under **Private keys**, click **Generate a private key**. A `.pem` file downloads. A separate key
   for this repo means you can revoke it without breaking claude-code-adw.

## Step 2. Make the two OpenRouter keys

The credit limit on each key is the hard spend stop
([ADR 0004](../adr/0004-per-key-credit-limits-as-the-spend-stop.md)). Once a key reaches its limit,
OpenRouter refuses its requests.

1. Buy about 20 USD of credit at <https://openrouter.ai/settings/credits>.
2. Open <https://openrouter.ai/settings/keys> and click **Create Key**.
   - Name: `harness-lab-github`.
   - Under **Key limit**, set **Credit limit** to `10`. Leave the reset interval empty: an empty
     reset makes the limit a lifetime cap, which is what the design wants. Leave
     **Include BYOK usage in limit** as it is; we bring no provider keys of our own.
   - Create it and copy the key. You need it in Step 4.
3. Create a second key the same way, named `harness-lab-local`, with a credit limit of `10`. Keep it
   in your password manager. It is for local runs and the daily groceries job. It never goes on
   GitHub, and it never goes in a committed file.

## Step 3. Make the subscription token

On your machine, with Claude Code installed and logged in to your subscription:

```bash
claude setup-token
```

Follow the browser prompt, and copy the token it prints. It is tied to your subscription, so the
factory's Claude Code runs count against your plan's usage limits, not against API billing.

Read the switch rule in the [factory doc](README.md#the-claude-code-login-and-the-switch-rule)
before you rely on this token. When a run would act on anyone else's issue or PR, the factory
refuses to start it on this token.

## Step 4. Store the values on the repository

Open the repository on GitHub, then **Settings**, **Secrets and variables**, **Actions**. Or use
the terminal, from a clone:

```bash
gh variable set FACTORY_APP_CLIENT_ID --body "Iv23li..."           # Client ID from Step 1
gh secret set FACTORY_APP_KEY < ~/Downloads/<app-name>.*.private-key.pem
gh secret set CLAUDE_CODE_OAUTH_TOKEN                               # prompts; paste Step 3's token
gh secret set OPENROUTER_API_KEY                                    # prompts; paste harness-lab-github
```

Then delete the downloaded `.pem` file, or move it into your password manager.

`FACTORY_CLAUDE_LOGIN` stays unset, so the factory starts on the subscription token. The other
knobs are in the [factory doc](README.md#knobs). Their defaults are fine to start with.

## Step 5. Create the labels

The factory adds and removes labels, and a step that adds a label it cannot find fails. From a
clone:

```bash
uv run python -m factory.sync_labels            # dry run: lists what it would create or fix
uv run python -m factory.sync_labels --apply    # creates and fixes them
```

It never deletes a label. Running it twice is safe.

## Step 6. Check two Actions settings

Under **Settings**, **Actions**, **General**:

- **Fork pull request workflows from outside collaborators**: choose
  **Require approval for all external contributors**. Fork PRs get no secrets either way. This
  setting also stops their CI runs from starting until you approve them.
- **Workflow permissions**: **Read repository contents and packages permissions**. The factory
  workflows declare their own permissions and use the App token for writes.

## Step 7. The live check

This proves each piece in a few cents: the workflows run, the preflight finds the configuration,
the App token mints, Claude Code answers on the configured login, and the App posts on the issue.

1. Open a test issue:

   ```bash
   gh issue create --title "Factory check" --body "Live check from the setup guide. Close when done."
   ```

2. Apply the test label to it: `gh issue edit <N> --add-label factory-check`.
3. Open the **Actions** tab. A **Factory check** run starts. Within a minute or two:
   - the run is green;
   - the issue has a comment from `<app-name>[bot]` that says Claude Code replied `factory ok` on
     the `subscription` login;
   - the `factory-check` label is gone, removed by `<app-name>[bot]`.
4. Optional: check the OpenRouter login too.
   1. Run `gh variable set FACTORY_CLAUDE_LOGIN --body openrouter`.
   2. Apply `factory-check` again. The comment should name the `openrouter` login, and
      <https://openrouter.ai/activity> should show the request on `harness-lab-github`.
   3. Run `gh variable delete FACTORY_CLAUDE_LOGIN` to go back to the subscription token.
5. Close the issue.

The factory is ready. The first real Ticket gets `ready-for-agent`.

## If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| No **Factory check** run at all | The label was not added by the repository owner, or the workflows are not on `main` yet | Add the label yourself, after the post 0 PR is merged |
| **Factory not configured: Missing ...** | A value from Step 4 is missing or misnamed | Check the names exactly, in both the Variables and the Secrets tabs |
| **Mint the factory App token** fails with `Not Found` | The App is not installed on this repository, or the Client ID is another App's | Redo Step 1.4, and check the Client ID |
| The token step fails with a key error | The secret is not the whole `.pem` file | Paste the whole file, both `-----` lines included |
| The **Ask Claude Code** step fails | The login's secret is wrong or expired, or the OpenRouter key is out of credit | Redo Step 3, or check the key on OpenRouter |
| **Post the answer** fails with `are the labels synced?` | Step 5 was skipped | Run Step 5 |
| **Daily run cap reached** | The workflow has started `FACTORY_DAILY_RUN_CAP` runs today (UTC) | Wait for tomorrow or raise the variable |

To stop the factory for a while, set `FACTORY_DAILY_RUN_CAP` to `0`. To cut it off completely,
remove `harness-lab` from the App's installation, or delete this repo's private key from the App's
settings.

## What was verified, and where

These facts were checked against the providers' own pages on 2026-11-06, for post 0.

**OpenRouter** (from OpenRouter's own docs; the Morph guide in the design was only secondhand):

- **Confirmed: the Anthropic-compatible endpoint.** OpenRouter "exposes an input that is
  compatible with the Anthropic Messages API". The Messages endpoint is
  `https://openrouter.ai/api/v1/messages`. For Claude Code, the base URL is
  `https://openrouter.ai/api`, with `ANTHROPIC_AUTH_TOKEN` set to the OpenRouter key and
  `ANTHROPIC_API_KEY` set explicitly empty.
  [Claude Code integration](https://openrouter.ai/docs/guides/coding-agents/claude-code-integration),
  [Create a message](https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-a-message).
  The guide also notes that Claude Code through OpenRouter "is only guaranteed to work with the
  Anthropic first-party provider".
- **Confirmed: per-key credit limits.** Each key has a **Credit limit** in USD, with an optional
  daily, weekly or monthly reset. Without a reset it is a lifetime cap. When a key's spend reaches
  its limit, its requests fail with `403 Forbidden` and `Key limit exceeded`.
  [Capping shared agent keys](https://openrouter.ai/docs/guides/best-practices/capping-shared-agent-keys),
  [Provisioning API keys](https://openrouter.ai/docs/features/provisioning-api-keys).
- **Model ids:** `anthropic/claude-haiku-5.5`, `anthropic/claude-sonnet-5.5`,
  `anthropic/claude-opus-5.5`.
  [Claude 5.5 migration guide](https://openrouter.ai/docs/cookbook/evaluate-and-optimize/model-migrations/claude-5-5).

**Anthropic** (from Anthropic's own pages; the design's source was press coverage):

- **Confirmed: subscription credentials are for Claude Code and Anthropic's own apps, not for
  other tools.** Claude Code's legal page says subscription OAuth "is designed to support ordinary
  use of Claude Code and other native Anthropic applications". Developers building products,
  "including those using the Agent SDK, should use API key authentication". Routing requests
  through Free, Pro, Max or Ultra plan credentials on behalf of users is not permitted.
  [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance). The usage policy
  lists "services that route requests through consumer subscriptions" under platform abuse.
  [Usage policy](https://www.anthropic.com/legal/aup). This supports
  [ADR 0002](../../projects/harness/docs/adr/0002-openrouter-only-provider-and-sole-credential.md): the harness never uses a
  subscription token.
- **Not confirmed: the February 2026 date and wording.** The Register (2026-02-20) quotes a
  sentence that forbids subscription tokens "in any other product, tool, or service — including the
  Agent SDK". That sentence is not on Anthropic's current page, and none of Anthropic's own pages
  dates the change. The substance stands. The date and the exact wording come only from the press.
- **Confirmed: Claude Code in GitHub Actions on a subscription token is documented.** Anthropic's
  GitHub Actions page describes `CLAUDE_CODE_OAUTH_TOKEN` as "an OAuth token that authenticates
  with your Claude subscription", generated with `claude setup-token`. It adds: "runs use your
  Claude subscription instead of API billing".
  [GitHub Actions](https://code.claude.com/docs/en/github-actions). The factory runs the Claude Code
  CLI itself, not the Agent SDK.
- **Partly confirmed: personal CI use.** No Anthropic page says outright that running Claude Code
  in CI on your own repo with your own subscription is allowed. What the pages do say: the token is
  documented for CI. It "is tied to the subscription of the person who ran `claude setup-token`".
  Advertised plan limits "assume ordinary, individual usage of Claude Code and the Agent SDK". The
  switch rule matches this: the subscription token is for the owner's own work only, and the
  factory moves to OpenRouter when someone else's work, a scheduled job, or heavy usage comes in.
- **Confirmed: the gateway variables.** `ANTHROPIC_BASE_URL` overrides the endpoint, and
  `ANTHROPIC_AUTH_TOKEN` is sent as `Authorization: Bearer`. While a gateway credential is set, it
  replaces the subscription login.
  [Environment variables](https://code.claude.com/docs/en/env-vars),
  [LLM gateway](https://code.claude.com/docs/en/llm-gateway).
