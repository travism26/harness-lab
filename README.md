# harness-lab

A small agent harness, built in public by a software factory on GitHub Actions, one blog post at a time.

Work arrives as GitHub issues. The owner labels a Ticket `ready-for-agent`, and the factory builds it as a draft PR, reviews it, and leaves the merge to a human.

- [Design brief](docs/design.md): the settled decisions for the series, harness and factory.
- [Glossary](GLOSSARY.md) and [decision records](docs/adr/): project terms and the hard-to-reverse choices.
- [The factory](docs/factory/README.md): how a Ticket becomes a draft PR, and the brakes. The owner's [setup guide](docs/factory/setup.md) wires its credentials.
- [Episode notes](docs/episodes/): one file per finished episode, from [the template](docs/episodes/TEMPLATE.md).
- [Software-factory research](docs/software-factory/README.md): notes consolidated from [claude-code-adw](https://github.com/travism26/claude-code-adw) at `b2e37ed`. The settled factory for this repo stays in the design brief.

## Running the tests

```bash
uv run pytest
```

Licensed under the [MIT License](LICENSE).
