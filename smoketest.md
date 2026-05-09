# CelloS Smoke Test (v5)

This is the smoke test for CelloS after the service extraction refactor.
It validates CLI entry point, database initialization, service wiring, worker subprocess spawning, and end-to-end task lifecycle.

**Total time: ~4 minutes**

## 1. Unit tests

```bash
python3 -m pytest -q
```

Expected: 102 passed.

## 2. CLI entry point

```bash
cellos --help
```

Expected: shows CLI group with commands: `init`, `add-task`, `status`, `events`, `detail`, `update`, `comment`, `approve`, `run`. (The `worker` command is hidden — it's only called via subprocess.)

## 3. Initialize

```bash
cellos init --hard-reset
cellos status
```

Expected:

- Config files created in `~/.cellos/`
- Database created in `.cellos/cellos.sqlite`
- `cellos status` shows no tasks

## 4. Create a task

```bash
cellos add-task "Test task" --role engineer
cellos status
```

Expected:

- Task created with status `draft`
- `cellos status` shows the task

## 5. Run scheduler (cellos run)

```bash
cellos run
```

Expected:

- No crash
- Exit code 0
- Output shows scheduler results (attention/planning/execution tasks)
- `SchedulerService.run_once()` executes

## 6. Task detail

```bash
cellos status
# note TASK_ID from output
cellos detail <TASK_ID>
```

Expected:

- Shows task title, status, role, prompt
- No errors

## 7. Events

```bash
cellos events
```

Expected:

- Shows event list table
- No errors

## 8. Worker subprocess (if scheduler scheduled a task)

If `cellos run` scheduled a planning task:

```bash
cellos status
# note TASK_ID
sleep 5
cellos detail <TASK_ID>
```

Expected:

- Task status changed (e.g., `in_progress` or `needs_approval`)
- Worker log exists at `.cellos/logs/worker-<TASK_ID>.log` with attempt details (prompt, result, summary)

## 9. End-to-end lifecycle test

Full task lifecycle: creation → approval → planning → child task creation via decomposition → dependency blocking → unblocking → execution → final result.

Uses the `fake_acp` connector (configured by default). Requires no external agents.

### 9a. Create a parent task that triggers child task decomposition

```bash
cellos add-task "Research prerequisites" --role researcher --prompt "CREATE_RESEARCH_CHILD_ACTION: Research the prerequisites for the main task and report findings."
PARENT_ID=$(cellos status | tail -1 | awk '{print $1}')
echo "PARENT_ID=$PARENT_ID"
```

Expected: task created with status `draft`.

### 9b. Approve the parent task

```bash
cellos approve $PARENT_ID
```

Expected: task status changes from `draft` to `approved`.

### 9c. Run scheduler — schedules parent for planning

```bash
cellos run
```

Expected: scheduler picks up the approved task, schedules it in planning mode.

### 9d. Wait for planning worker, verify result

```bash
sleep 5
cellos detail $PARENT_ID
```

Expected:

- Task status is `needs_approval` (planning worker produced a plan)
- A child task was created with `blocks_parent: true`
- Events show: `task_scheduled`, `attempt_started`, `attempt_completed`, `planning_saved`, `task_marked_needs_approval`

### 9e. Approve the child task

```bash
CHILD_ID=$(cellos status | grep researcher | tail -1 | awk '{print $1}')
cellos approve $CHILD_ID
```

Expected: child task status changes to `approved`.

### 9f. Approve the parent task again (approve the plan)

```bash
cellos approve $PARENT_ID
```

Expected: parent is approved for execution.

### 9g. Run scheduler — schedules both for execution

```bash
cellos run
```

Expected: scheduler picks up both approved tasks. Parent is `BLOCKED` (child not done yet). Child is scheduled for execution.

### 9h. Wait for child worker, verify blocking and unblocking

```bash
sleep 5
cellos status
cellos detail $PARENT_ID
```

Expected:

- Child task is `done`
- Parent task is no longer blocked, status is `approved` (dependency satisfied)
- Events show dependency unblock

### 9i. Run scheduler — schedules parent for execution

```bash
cellos run
```

### 9j. Wait for parent execution, check final result

```bash
sleep 5
cellos detail $PARENT_ID
```

Expected: parent is `done`, result summary present.

### 9k. Full event audit

```bash
cellos events
```

Expected: complete audit trail from creation through execution.

### 9l. Invalid child action test

```bash
cellos add-task "Test invalid action" --role engineer --prompt "CREATE_INVALID_CHILD_ACTION: This should produce an invalid action."
INVALID_ID=$(cellos status | tail -1 | awk '{print $1}')
cellos approve $INVALID_ID
cellos run
sleep 5
cellos detail $INVALID_ID
```

Expected: task shows failure/invalid action, not a crash.

## 10. Agent selection

Per-task ACP agent assignment via `--agent` and `--clear-agent`.

### 10a. Create task with specific agent

```bash
cellos add-task "Agent test task" --agent fake --config ~/.cellos/config.json
AGENT_TASK_ID=$(cellos status | tail -1 | awk '{print $1}')
```

Expected: task created with `agent_id` set to `fake`.

### 10b. Verify agent in detail view

```bash
cellos detail $AGENT_TASK_ID
```

Expected: output includes `Agent: fake`.

### 10c. Clear agent — falls back to default

```bash
cellos update $AGENT_TASK_ID --clear-agent
cellos detail $AGENT_TASK_ID
```

Expected: `Agent:` line no longer present. Worker will use `config.agents.default`.

### 10d. Invalid agent rejected at create time

```bash
cellos add-task "Bad agent task" --agent nonexistent_agent 2>&1
```

Expected: `ClickException` with message about agent not in catalog. Exit code 1.

### 10e. Mutually exclusive flags

```bash
cellos update $AGENT_TASK_ID --agent fake --clear-agent 2>&1
```

Expected: `ClickException` — "Use either --agent or --clear-agent, not both." Exit code 1.

## 11. Comments and attention

Human comments trigger attention on tasks.

### 11a. Add a comment to a task

```bash
cellos comment $PARENT_ID "This is a human comment"
```

Expected: comment recorded, task marked with `attention_required`.

### 11b. Verify comment in detail view

```bash
cellos detail $PARENT_ID
```

Expected: "Recent Comments" section shows the comment with author `human`.

## 12. Explicit dependencies

`--depends` on create and `--depends`/`--remove-dep` on update.

### 12a. Create two independent tasks

```bash
cellos add-task "Dependent task"
DEP_TASK_ID=$(cellos status | tail -1 | awk '{print $1}')
cellos add-task "Dependency task"
DEP_ON_ID=$(cellos status | tail -1 | awk '{print $1}')
```

### 12b. Add dependency after creation

```bash
cellos update $DEP_TASK_ID --depends $DEP_ON_ID
cellos detail $DEP_TASK_ID
```

Expected: `Dependencies: $DEP_ON_ID` shown in detail.

### 12c. Remove dependency

```bash
cellos update $DEP_TASK_ID --remove-dep $DEP_ON_ID
cellos detail $DEP_TASK_ID
```

Expected: `Dependencies:` line absent or empty.

## 13. Invalid approval guard

Approving a task that is not in `needs_approval` should fail.

### 13a. Try approving a draft task

```bash
cellos add-task "Draft for invalid approval"
DRAFT_ID=$(cellos status | tail -1 | awk '{print $1}')
cellos approve $DRAFT_ID 2>&1
```

Expected: `ClickException` — approval fails because task is not `needs_approval`. Exit code 1.

### 13b. Approving non-existent task

```bash
cellos approve deadbeef 2>&1
```

Expected: `ClickException` — task not found. Exit code 1.

## 14. Empty update guard

Updating a task with no changes should fail.

### 14a. Update with no fields

```bash
cellos update $PARENT_ID 2>&1
```

Expected: `ClickException` — empty update rejected. Exit code 1.

## 15. Change-request flow

When a child task fails with `change_requested`, the parent gets attention.

### 15a. Create a parent task

```bash
cellos add-task "Parent for change request" --role architect
PARENT_CR_ID=$(cellos status --quiet 2>/dev/null | tail -1 | awk '{print $1}')
cellos approve $PARENT_CR_ID
```

### 15b. Run scheduler — schedules parent for planning

```bash
cellos run
sleep 5
```

### 15c. Approve the plan, then create a child that will fail

```bash
cellos approve $PARENT_CR_ID
cellos run
sleep 5
```

Expected: parent is `done` or child task created and executed. No crash.

### 15d. Verify events for change-request or failure

```bash
cellos events --limit 50
```

Expected: events show the full chain — scheduling, attempts, results. No unhandled exceptions.

## What changed from v4

- Updated test count: 102 passed (was 93)
- Added Step 10: Agent selection (`--agent`, `--clear-agent`, invalid agent rejection, mutually exclusive flags)
- Added Step 11: Comments and attention
- Added Step 12: Explicit dependencies (`--depends`, `--remove-dep`)
- Added Step 13: Invalid approval guard (draft task, non-existent task)
- Added Step 14: Empty update guard
- Added Step 15: Change-request flow verification

## If any step fails

| Step | Likely cause |
|------|--------------|
| 1 | Import errors, missing dependencies |
| 2 | `pyproject.toml` entry point broken |
| 3 | Database/config initialization failure |
| 4 | `TaskService` not wired correctly |
| 5 | `SchedulerService` not wired or subprocess entrypoint broken |
| 6 | `CellosDatabase` query or `detail_formatter` broken |
| 7 | `CellosDatabase` event queries broken |
| 8 | `WorkerSpawner` subprocess command wrong, or `WorkerService` missing |
| 9a-9l | Service wiring, dependency logic, or fake ACP connector broken |
| 10a-10e | `agent_id` field missing from Task model, `get_agent()` broken, CLI flag wiring |
| 11a-11b | Comment recording or attention marking not wired |
| 12a-12c | Dependency add/remove in `TaskService.update_task()` |
| 13a-13b | Approval validation in `TaskService.approve_task()` |
| 14a | Empty update guard in `TaskService.update_task()` |
| 15a-15d | Change-request handling in `ExecutionService` |
