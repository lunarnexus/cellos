# Step 2 — Real-time daemon behavior and tests

Source: `docs/plans/2026-06-30-cellos-usefulness-improvement-list.md`

## Goal
Make the daemon behave like the main runtime, not a best-effort loop, and prove that behavior with tests.

## Scope for this execution
1. Verify daemon wake behavior from runtime events and human actions.
2. Verify ready-work progression after dependency completion.
3. Make provider auto-pull timing deterministic.
4. Prevent provider pull from silently making tasks executable without visible audit/attention.
5. Expand test coverage around the above and rerun targeted + full suite.

## Planned work
1. Add daemon/runtime tests for:
   - worker completion wakes the daemon
   - notification-file watcher wakes on touched file
   - dependency completion leaves downstream work runnable on next cycle
2. Tighten provider auto-pull behavior:
   - respect `pull_interval_seconds`
   - cover first-pull vs skipped-pull behavior in tests
3. Tighten provider pull safety semantics:
   - when remote status changes local task into an executable state, add visible audit
   - require attention when provider pull transitions a task into `approved`
   - cover with Vikunja provider tests
4. Run targeted tests for scheduler/provider/CLI surfaces touched.
5. Run full suite.
6. Run final correctness/security review subagents.

## Acceptance criteria
- Daemon wake paths are covered by explicit tests.
- Auto-pull timing is deterministic and tested.
- Provider pull cannot silently make a task executable without visible audit/attention.
- Dependency-unblock path is covered by executable tests.
- Targeted tests pass.
- Full suite passes.

## Stop conditions
- If fixing one area requires a larger workflow redesign outside Step 2, stop and report.
- No new CLI commands in this step unless a test proves they are required.
