# The factory starts from an approved Spec, and fork PRs get no secrets

The repo is public and the factory holds secrets. Opening an issue starts nothing. Fork pull requests never get secrets. A Ticket starts when the factory App adds `factory:start`, and the App adds it only for a hand Ticket the owner approved with `owner:implement` or for a child of a Spec that wears `owner:implement`. The claim comment names that approval. The per-ticket owner label is gone: with the Builder acting as the owner, that label was not a record of who decided.

This makes the factory slower to start than reacting to every issue, but anyone can open an issue or a pull request on a public repo and none of them should be able to spend credit or reach credentials.
