# Label-only factory start, and no secrets for fork PRs

The repo is public and the factory holds secrets, so it starts only on a label the owner applies, never when an issue opens. PRs from forks never get secrets. This makes the factory slower to start than reacting to every issue, but anyone can open an issue or PR on a public repo and none of them should be able to spend credit or reach credentials.
