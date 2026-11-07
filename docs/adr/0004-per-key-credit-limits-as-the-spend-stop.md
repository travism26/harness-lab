# Per-key credit limits as the hard spend stop

About 20 USD in total is spent on OpenRouter, split across two keys, each with its own credit limit: 10 USD for GitHub test runs, and 10 USD for local runs and the daily groceries job. The limit on the key is the hard stop, rather than a check in our own code, because a bug in our code cannot lift a limit enforced by the provider. The split keeps a runaway factory run from using up the budget of the local runs.

**Amended for the lab ([0008](0008-one-repo-one-factory-projects-in-projects-dir.md)):** each project gets its own OpenRouter key per environment, one for GitHub runs and one for local runs, and each key has its own credit limit. One project's runaway run cannot spend another project's budget.
