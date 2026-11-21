# Experiment request: synthetic example

## Hypothesis

The synthetic release note claims that trivial commands succeed.

## Public sources

- https://example.com/release-notes (synthetic source)

## Checks

Each check is a trivial shell command.

### 1. True succeeds

```sh
true
```

Pass means: the command exits 0.

### 2. The folder exists

```sh
test -d .
```

Pass means: the request folder exists.

## Cost cap (USD)

0.25

## Timebox (minutes)

5

## Model / login

subscription

## Revert

Delete the synthetic branch.
