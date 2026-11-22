# Experiment request: synthetic example

## Hypothesis

The synthetic release note claims that trivial commands succeed.

## Public sources

- https://example.com/release-notes (synthetic source)

## Checks

Each check is a trivial shell command.

### 1. Succeeds

```sh
true
```

Pass means: exit 0.

### 2. Fails with one

```sh
false
```

Pass means: never.

### 3. Fails with three

```sh
exit 3
```

Pass means: never.

## Cost cap (USD)

0.25

## Timebox (minutes)

5

## Model / login

subscription

## Revert

Delete the synthetic branch.
