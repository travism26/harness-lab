# harness

The harness project's own terms. Lab-wide terms (Factory, Ticket and the rest) are in the [root glossary](../../GLOSSARY.md).

## Language

**Harness**:
The small program in this repo that runs a model in a tool loop. It is the thing the series teaches.
_Avoid_: Agent framework, bot

**Episode**:
One numbered stage of the series (0 to 5), delivered as a set of tickets and one post.
_Avoid_: Chapter, part, milestone

**Post 0**:
The first episode, which sets up the factory through the skeleton PR.
_Avoid_: Bootstrap post, intro

**Post**:
The blog article for an episode, written in the author's voice in the separate blog repo.
_Avoid_: Article, write-up

**Episode notes**:
The file the factory writes in this repo when an episode finishes: what was built, what broke, key snippets, PR links. Source material for the post.
_Avoid_: Changelog, summary

**Run**:
One execution of the harness on one question, from the question to a stop (final answer, turn cap, provider error or refused tool call). Each Run writes one Run log.
_Avoid_: Session, job, conversation

**Turn**:
One request to the model and its reply, within a Run. A Run has at most the turn cap of Turns.
_Avoid_: Step, iteration, round (a Rework round is a different, lab-wide term)

**Tool call**:
The model's request, in a reply, to run one of the harness's tools with given input.
_Avoid_: Function call, action

**Tool result**:
What the harness sends back to the model for a Tool call: the tool's output, or its error.
_Avoid_: Observation, tool output

**Run log**:
The JSON-lines file a Run writes under `projects/harness/runs/`, one event per line: each request, reply, Tool call, Tool result and the stop.
_Avoid_: Transcript, trace, history
