# Rules

## secret-shaped

Reports a line of a scanned file that matches the credential expression. The location is `secret`. The matched text is never printed.

The expression is `CREDENTIAL_RE` at `factory/research_note.py` lines 25-29. This Project holds its own copy and does not import `factory`; a test checks the copy has not drifted.

Findings are heuristic, and a clean scan is not a security guarantee.
