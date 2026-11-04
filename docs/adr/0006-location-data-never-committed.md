# Location data is never committed

Area, postal code and chosen stores for the groceries job live only in an uncommitted local file, or in a repo secret if the job ever runs on GitHub. The repo holds only the fake store site and example settings. The repo is public and history is hard to rewrite, so keeping personal location out of it from the start is cheaper than removing it later.
