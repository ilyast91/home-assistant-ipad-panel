# Implement the iPad panel

1. Write unit tests for settings, read-only client, caching on errors, privacy, escaping, and browser-safe refresh. Run them against the empty implementation (red).
2. Implement the small shared Python service and server-rendered UI; run tests (green). Use the standard library and JSON for both configurations.
3. Add one Dockerfile in the HAOS App directory and Compose targeting that directory. Add repository/app metadata, `.env.example`, a JSON example, documentation, and a CI workflow.
4. Validate metadata, render Compose config, build the shared image for the local architecture and exercise demo and both configuration paths against a fake HA. Review the diff for secrets and scope.
5. Commit and push to a new public GitHub repository, then verify remote visibility and branch. Do not claim physical iPad or Supervisor verification.
