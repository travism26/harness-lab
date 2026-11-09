# Live validation through the Broker, 2026-11-09

Issue #93, the live check for spec #85 ("The Agent holds no secrets"). Claude ran it on the owner's laptop against a real spiffecli Workload API and the live Anthropic Model, 2026-11-09 12:34–12:35 (UTC−4). The Broker ran as its own process and held the provider key. The demo and the Eval ran in environments that held no provider key and could reach no `.env`.

- Revision: `5fe1ff9` (branch `agent-identity-broker`, PR #94)
- Go: `go1.27.3 darwin/arm64`
- spiffecli: `0.1.3` (commit `fe1b9e7`), with the `permission-agent`, `warden`, `model-broker`, `model-eval` and `unlisted-agent` workloads from `projects/agent-identity/spiffecli/workloads.toml`
- Provider: Anthropic (the Broker's default, because its key was present). OpenRouter was not used. Model: `claude-haiku-5-5`
- Cost of the run: about $0.0002 (two Model calls)

## How it was run

The three programs were built once with `go build` to `/tmp/ai93/bin/`, so no `go run` process sat between the shell and the program.

1. `spiffecli run --config spiffecli/workloads.toml`, from `projects/agent-identity/`.
2. The Broker, from `projects/agent-identity/`, where it alone reads `.env`:

   ```
   /tmp/ai93/bin/broker --out runs/live-2026-11-09-broker
   broker: provider anthropic
   broker: Audit log <run-dir>/broker.audit.jsonl
   broker: listening on http://127.0.0.1:8787 (demo: --live --broker-url http://127.0.0.1:8787 --out <run-dir>)
   ```

3. The demo and the Eval, each started with `env -i PATH=/usr/bin:/bin HOME=$HOME` from an empty directory, `/tmp/ai93/work`. Each one printed its own environment's variable names first, then `exec`ed the program in that same environment.

`<run-dir>` stands for `projects/agent-identity/runs/live-2026-11-09-broker` (gitignored). Its three logs are committed unchanged in [live-broker-2026-11-09/](live-broker-2026-11-09/).

## Neither environment holds a key

```
== demo env (names)
HOME PATH PWD SHLVL _
== key vars in demo env: 0
== cwd /private/tmp/ai93/work:
.
..
```

```
== key vars in Eval env: 0; cwd has .env: 0
```

The Claude Code shell that started everything also held neither `ANTHROPIC_API_KEY` nor `OPENROUTER_API_KEY` (the count was 0). The only copy of the key was `projects/agent-identity/.env`, read by the Broker process alone. trustlint R5 holds the same property for the code: no package outside the Broker can read a key.

## `tour --live` through the Broker

```
$ demo tour --live --broker-url http://127.0.0.1:8787 --out <run-dir> \
    --spiffe-socket /tmp/agent-identity/permission-agent.sock \
    --spiffe-socket-other /tmp/agent-identity/unlisted-agent.sock
== tokens
POST /lookup  agent=spiffe://example.com/permission-agent  aud=spiffe://example.com/warden  -> 200  outcome=answer_yes
POST /lookup  agent=spiffe://example.com/permission-agent  aud=spiffe://example.com/not-the-warden  -> 401  outcome=unauthenticated  reason=jwt_svid_audience
POST /lookup  agent=spiffe://example.com/unlisted-agent  aud=spiffe://example.com/warden  -> 403  outcome=agent_not_allowed
== scripted
POST /lookup  caller=acme/alice  target=acme/tom  permission=invoice:approve  -> 200  outcome=answer_yes  holds=true  role=Finance Approver
POST /lookup  caller=acme/bob  target=acme/tom  permission=invoice:approve  -> 403  outcome=denial  failed_check=lookup_check
POST /lookup  caller=acme/alice  target=globex/sam  permission=permission:read  -> 403  outcome=denial  failed_check=lookup_check
== ask
level=INFO msg=proposal target=tom permission=invoice:approve model_calls=1 correlation_id=f525cb141039621e2492b5ef910c6c42
level=INFO msg=broker status=200 outcome=allowed
level=INFO msg=warden status=200 outcome=answer_yes
level=INFO msg=reply id=yes correlation_id=f525cb141039621e2492b5ef910c6c42
Yes. tom holds `invoice:approve` in acme through the Finance Approver role.
[model: anthropic/claude-haiku-5-5 via broker · id f525cb141039621e2492b5ef910c6c42]
== broker
note: skipped: a live run uses the separate Broker process, not the stand-in one
```

Exit 0. The footer shows `via broker`, and the Broker named the provider and model. The `warden listening` lines and timestamps are cut from the log lines above. The live tour skips the stand-in `broker` scenario by design. The Broker's 401 and 403 refusals are held offline by its handler tests and the stand-in tour ([tour.txt](tour.txt)). They were not run live.

## One Eval case as `model-eval`

The first case of `projects/agent-identity/evals/cases.jsonl` (`named-tom-approve`), one run, report-only:

```
$ eval --broker-url http://127.0.0.1:8787 --model claude-haiku-5-5 --cases one-case.jsonl --runs 1 --min-accuracy 0
eval: asking the Broker at http://127.0.0.1:8787 for model claude-haiku-5-5
provider: anthropic
model: claude-haiku-5-5
runs per case: 1
min accuracy: 0.00

category      passed/runs  accuracy  retries
named             1/1        100.0%  0

unstable cases: none
total cost: $0.000102 (anthropic)
result: PASS
```

Exit 0. The report's provider and model are the ones the Broker reported. The raw reply (cut here) was a single `lookup_permission` tool call for `tom`, `invoice:approve`.

## The three logs join on one Correlation ID

All three logs from the run are in one directory. The Agent's and the Warden's logs have 7 records each, joined one-to-one by Correlation ID. The Broker's log has 2 records: the tour's question and the Eval case. The six `tokens` and `scripted` lookups make no Model call, so they have no Broker record.

For the question `f525cb141039621e2492b5ef910c6c42`, copied unchanged:

```json
{"ts":"2026-11-09T16:34:56.767301Z","correlation_id":"f525cb141039621e2492b5ef910c6c42","spiffe_id":"spiffe://example.com/permission-agent","provider":"anthropic","model":"claude-haiku-5-5","outcome":"allowed","status":200,"request_id":"req_011CgsgJCSdZigXN9YaNzQQj","input_tokens":635,"output_tokens":78,"cost":0.0001025}
{"ts":"2026-11-09T16:34:56.769452Z","correlation_id":"f525cb141039621e2492b5ef910c6c42","status":200,"outcome":"answer_yes","agent":"spiffe://example.com/permission-agent","caller":"acme/alice","target":"acme/tom","permission":"invoice:approve","role":"Finance Approver"}
{"ts":"2026-11-09T16:34:56.769593Z","correlation_id":"f525cb141039621e2492b5ef910c6c42","caller_unverified":"acme/alice","question":"Can Tom approve invoices?","backend":"live","model":"claude-haiku-5-5","attempts":1,"proposal":{"target":"tom","permission":"invoice:approve"},"warden_status":200,"reply":"yes","model_calls":[{"request_id":"req_011CgsgJCSdZigXN9YaNzQQj","provider":"anthropic","cost":0.0001025,"model":"claude-haiku-5-5","input_tokens":635,"output_tokens":78,"broker_reported":true}]}
```

These are the Broker's, the Warden's and the Agent's records, in the order they were written. The Broker's record carries Anthropic's request id, the token counts and the cost. The Agent's record copies them, marked `broker_reported`. The Broker's record names the caller's SPIFFE ID and never the Caller: only the Warden's record has `caller`.

The Eval's Broker record has `spiffe_id` `spiffe://example.com/model-eval`, its own Correlation ID, request id `req_011CgsgJtdMCtNBdcAQuAp3A`, 635 input and 78 output tokens, and a cost of $0.0001025.

## No key and no JWT-SVID in the evidence

`TestLiveBrokerRunLogs` in `projects/agent-identity/cmd/demo/evidence_test.go` holds the committed logs. It decodes each one strictly against its record struct, checks the joins and the Broker's request ids, tokens and cost, and runs the JWT-shape and key-shape checks on all three files. The request ids are Anthropic's, not credentials.
