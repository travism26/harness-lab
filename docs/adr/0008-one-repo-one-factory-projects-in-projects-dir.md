# One repo, one shared factory, projects in `projects/<name>/`

The lab is one repository with one factory. Each project lives in `projects/<name>/` with its own glossary, decision records and check, and the factory's scripts, workflows and brakes stay at the root, shared by all of them. If a project ever needs its own repository, split it out with `git subtree split`, which keeps its history.

Separate repositories per project were weighed and rejected: each would need its own copy of the factory and its brakes, and those copies would drift apart.

To add a project, create `projects/<name>/` and add its tests to `testpaths` and its `src` to `pythonpath` in the root `pyproject.toml`.
