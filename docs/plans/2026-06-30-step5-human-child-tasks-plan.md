# Step 5 — Human-created child tasks

Source: `docs/plans/2026-06-30-cellos-usefulness-improvement-list.md`

## Goal
Let humans create child tasks directly from the CLI while preserving the same parent/child/dependency model used by agent-created tasks.

## Current gap
The CLI can create tasks with `--depends`, but there is no clean parent/child creation path for human decomposition. The data model already has `parent_id` plus `dependencies`.

## Target slice
1. Add CLI support for creating a child task from an existing parent.
2. Ensure the created task stores `parent_id`.
3. Also add the parent -> child dependency edge where appropriate so the parent stays blocked until the child completes.
4. Reuse existing task creation/update services rather than inventing a separate model path.
5. Add CLI + service/integration tests.

## Likely files
- `cellos/cli.py`
- `cellos/services/task_service.py`
- `tests/test_cli.py`
- `tests/test_integration.py`

## Acceptance criteria
- human can create a child task in one CLI command
- child task records parent relationship
- parent reflects dependency on child
- existing dependency behavior remains intact
- full tests pass
