# Experiment request: synthetic example

## Hypothesis

The synthetic release note claims that trivial commands succeed.

## Public sources

- https://example.com/release-notes (synthetic source)

## Checks

Each check is a trivial shell command.

### 1. Quick

```sh
true
```

Pass means: exit 0.

### 2. Slow

```sh
sleep 30
```

Pass means: never.

### 3. After

```sh
true
```

Pass means: exit 0.

## Cost cap (USD)

0.25

## Timebox (minutes)

1

## Model / login

subscription

## Revert

Delete the synthetic branch.
