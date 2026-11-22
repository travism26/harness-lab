# Map: a ClickHouse Project the factory builds

## Destination

A spec issue for a new ClickHouse-learning Project under `projects/`, plus its Tickets: the bootstrap Ticket ready for the owner to label, and any factory-root Tickets the Project needs (for example, giving a check a ClickHouse to run against). The map stops there. The factory does the building.

## Notes

- **Domain.** Podcast ad measurement on ClickHouse, continuing an existing experiment. The Project is for learning ClickHouse as a real app.
- **Planning only.** Tickets here resolve decisions. Nothing under `projects/` is written by this map.
- **Skills.** `grilling` and `domain-modeling` for every grilling ticket; `research` for research tickets; `prototype` for the README ticket.
- **Settled while charting.** The Project's check runs against real ClickHouse behaviour: a server or an embedded real engine. The language is Python or Go.

## Decisions so far

- What the factory's agent can run during its build turn: the agent's shell is unrestricted, so it can already start Docker or reach a service container.
- ClickHouse client libraries for Python and Go: each language has an official, maintained client.
- Ways to run real ClickHouse inside a check: a service container, the check starting the pinned image, the pinned binary and an embedded engine all ran the experiment's schema.

## Not yet specified

- The spec and its Ticket slicing: which thin first slice the bootstrap Ticket builds, and how the later Tickets are cut.
- Python or Go for the Project.
- How the Project's check gets ClickHouse, and what the check rule says about a pinned service.
- How the Project is bootstrapped, and how it reads in the public README.
- Whether a hosted runner can measure ClickHouse at all.
