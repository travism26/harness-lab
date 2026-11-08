# harness-lab

A lab where a software factory builds small projects, built in public. Work arrives as GitHub issues: the owner labels a Ticket `ready-for-factory`, and the factory builds it as a draft PR, reviews it, and leaves the merge to a human.

- [Harness](projects/harness/): a small agent harness, one blog post per episode. Start at its [README](projects/harness/README.md).
- [Glossary map](GLOSSARY-MAP.md), the lab [glossary](GLOSSARY.md) and [decision records](docs/adr/): terms and the hard-to-reverse choices.
- [The factory](docs/factory/README.md): how a Ticket becomes a draft PR, and the brakes. The owner's [setup guide](docs/factory/setup.md) wires its credentials.
- [Software-factory research](docs/software-factory/README.md): notes consolidated from [claude-code-adw](https://github.com/travism26/claude-code-adw) at `b2e37ed`. The settled factory for this repo stays in [the factory doc](docs/factory/README.md) and the [decision records](docs/adr/).

## Running the tests

```bash
uv run pytest
```

This runs the factory's tests and every project's tests. Licensed under the [MIT License](LICENSE).
