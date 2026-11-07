# The Model only proposes; every Reply is a fixed template

The Model turns the Caller's question into a Proposal (`{target, permission}`) and does nothing else. It never sees what the Warden returns, and the Agent builds every Reply from a fixed template based on the Answer, the Denial or the failure. A text-only reply from the Model is never shown to the Caller; it goes to the audit log, and the Caller gets the fixed "no lookup was made" Reply.

- The point of the Project is that the Model cannot grant, widen or guess a Permission. A second Model call that writes the explanation from the Answer could still say "yes" when the Warden said no, and it would put Warden output into the Model's context. With templates, that can't happen.
- A text-only reply can be a guess ("Yes, Tom can approve invoices") as easily as a clarifying question, and the Agent can't tell which, so it shows neither.
- It halves the Model calls per question and keeps the Replies testable by exact string.

## Considered options

- **Propose and explain:** two Model calls, the second writing prose from the Answer. Reads more naturally, but the Model could misstate the Answer.
- **Explain plus a fixed verdict line:** the Model's prose with an Agent-added line carrying the real Answer. Safer, but the two could still contradict each other in front of the Caller.

## Consequences

Replies read like templates, and the README says so. The proposal's line "the model interprets the question and explains the answer" no longer holds: the Model interprets, the Agent explains.
