# Skill chain

The planning chain reuses Matt Pocock's skills in his order. It does not copy them. `/ask-matt` names this sequence and does not run it. The wrapper is what runs it.

1. `/grill-with-docs` calls `grilling` and `domain-modeling`, then stops.
2. `/to-spec` writes the spec. His skill says to check the test seams with the user. The wrapper answers that and records the answer.
3. `/to-tickets` publishes the tickets. His skill waits for the user to approve the breakdown. The wrapper approves it and records the answer. The tickets get `ready-for-agent` only. That label does not start this factory.
4. Stop. The user adds `ready-for-factory` when a ticket should be built. That label does start the factory.

The factory then implements and reviews. Do not run `/implement-spec`. That skill marks a pull request ready. This factory keeps drafts until the user merges.

The trigger is a goal on an issue. A bot is not required to send that goal.

Out of this page: the RSS watch, webhook setup, and any edit to his skill files.
