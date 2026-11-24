# Spec: measure the factory with Run records, a metrics report and a backfill

## Problem Statement

The factory has built and reviewed dozens of Tickets, and I merged every one, but I cannot say how well it is doing. What a Factory run cost, how many turns it took and how many tokens it used exist only in the run's uploaded artifact, which GitHub deletes after 90 days. Runs that fail, and Review runs that finish after I have merged, leave nothing readable at all.

## Solution

Every Factory run leaves one small Run record: what ran, on which Ticket or pull request, with which login and model, how it ended, and what it cost in dollars, turns, tokens and time. The record lives in a hidden marker on a comment the factory bot posts, so it lasts as long as the Ticket does.

One command reads those records, together with labels, comments and CI runs, and prints a table: one row per factory Ticket and a totals row. A one-off backfill builds records for the Factory runs that happened before the record existed.

## User Stories

1. As the lab owner, I want an Implement run to leave a record, so that I know what building a Ticket cost.
2. As the lab owner, I want a Rework run to leave its own record, so that the cost of a Rework round is not hidden inside Review's.
3. As the lab owner, I want every Review run to leave a record, including Review of my own branches, so that I see all Review spend.
4. As the lab owner, I want a failed Factory run to leave a record too, so that failures are counted.
5. As the lab owner, I want one metrics command that prints a row per Ticket, so that I can see what each Ticket cost.
6. As the lab owner, I want a backfill for past runs, so that the history is not lost when the artifacts expire.

## Implementation Decisions

The work is cut into six Tickets, one per step: the Implement record, the Rework record, the Review record, the metrics report, the report's labels, CI and git columns, and the backfill. Each Ticket is its own pull request, and the later ones depend on the record shape the first one fixes.
