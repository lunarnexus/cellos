# Step 6 — Recovery / operator commands

Source: `docs/plans/2026-06-30-cellos-usefulness-improvement-list.md`

## Goal
Give operators explicit CLI recovery tools for tasks that get stuck or need manual intervention, instead of relying only on automatic daemon recovery paths.

## Current gap
Recovery behavior exists in worker/daemon flows, but operator-facing commands are thin. We need direct commands for inspecting state and safely restoring tasks.

## Target slice
1. Identify the highest-value operator command(s) already implied by the model/state machine.
2. Prefer minimal commands over a large recovery surface.
3. Reuse TaskService/DB state transitions rather than ad hoc SQL.
4. Add tests for failure-safe behavior and clear CLI output.

## Likely files
- `cellos/cli.py`
- `cellos/services/task_service.py`
- `tests/test_cli.py`
- `tests/test_integration.py`

## Acceptance criteria
- operator can recover a stuck task with a supported CLI path
- invalid transitions fail clearly
- audit trail remains intact
- full tests pass
