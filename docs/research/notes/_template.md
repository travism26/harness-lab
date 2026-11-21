# <the question, as a short title>

<!--
A Research note: the cited answer to one Research request (docs/factory/README.md, "Research path").
The factory's research agent writes every section except Cost, which the factory writes itself.
`factory/research_note.py` checks the file before anything is published. It skips this template,
because the name starts with an underscore. Comments like this one are ignored by the check.
-->

## Question

<!-- The one question from the request, in its own words. -->

## Findings

<!-- The answer. Each claim names the source it rests on, by its URL from Sources. Say plainly when
the sources disagree, and when a claim comes only from the company selling the thing. -->

## Sources

<!-- One list item per source, in this shape:

- [vendor] https://example.com/docs/thing: what this source supports
- [independent] https://example.org/study: what this source supports

`[vendor]` is a company or project describing its own product, prices or results. `[independent]`
is anyone who is not selling the thing described. Every source is a public `https://` page that
was read for this note. Each item carries exactly one of the two tags. -->

## Unknowns

<!-- What the sources did not establish: what could not be found, could not be confirmed, or was
out of reach from public pages. This section is never empty and never just "none". -->

## Cost

<!-- Written by the factory, not by the agent. Spend is the Claude Code CLI's own list-price figure
for the run, an estimate on every login, so it is marked `client-estimate`. Cap is the run's
`--max-budget-usd`. The check fails a note whose spend is over its cap.

- Spend: $0.00 (client-estimate)
- Cap: $2.00
-->
