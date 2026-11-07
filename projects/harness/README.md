# harness

A small agent harness, built in public by the lab's software factory on GitHub Actions, one blog post at a time.

- [Design brief](docs/design.md): the settled decisions for the series and the harness.
- [Glossary](GLOSSARY.md) and [decision records](docs/adr/): the harness's terms and choices. Lab-wide ones are in the [root glossary](../../GLOSSARY.md) and [decision records](../../docs/adr/).
- [Episode notes](docs/episodes/): one file per finished episode, from [the template](docs/episodes/TEMPLATE.md).

## Running the tests

From this directory:

```bash
./check
```

or run `uv run pytest` at the repo root, which also runs the factory's tests.
