# The metrics report crashes on a Ticket with no Run record

## What happens

Running the metrics report on a Ticket that has a Factory comment but no Run record in it stops with a traceback:

```
KeyError: 'outcome'
```

The report prints nothing for any Ticket after that one, so the totals row is never shown.

## What I expected

A Ticket with no Run record should get a row of dashes and a note, and the report should carry on to the next Ticket and print the totals.

## How to reproduce

1. Pick a Ticket whose Factory comment predates the Run record.
2. Run the metrics report with that Ticket in the range.
3. See the traceback.

It worked last week, before the report started reading comments as well as labels.
