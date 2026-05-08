# Scheduler Behavior

This document describes the scheduler logic that runs when `cellos run` is invoked.
The implementation is in `cellos/services/scheduler.py` (`SchedulerService.run_once()`).

`cellos run` is one bounded scheduler heartbeat. It should be safe to run repeatedly from a CLI command, cron job, launchd job, systemd timer, webhook handler, or future daemon.

The heartbeat does not run forever. It performs one scan/sync/evaluation/execution pass, records state, then exits.

## Goals

- Keep each run cheap when nothing changed.
- Avoid spawning LLM workers unless a task has a new reason for attention or approved executable work.
- Continue independent work when one integration or task fails.
- Make repeated invocations safe and predictable.
- Treat project-management tools as interfaces, not as the source of orchestration truth.

## Best Effort

If one adapter, task, or worker fails, CelloS should:

- record the error,
- continue independent work where possible,
- avoid crashing the whole heartbeat unless local state cannot be handled safely.

## Polling First

Assume the worst case: project-management tools may not reliably notify CelloS about every edit.

Some tools support webhooks, but they can fail, be delayed, or require setup. Therefore the core design must work by polling:

```text
heartbeat polls PM state -> detects changes -> updates local CelloS state
```

Webhooks can later trigger heartbeats sooner, but polling remains the baseline.

## Scheduler Order

One heartbeat runs in this order:

1. Load configuration.
2. Open the local database.
3. Load enabled PM adapters.
4. Sync known PM-linked tasks.
5. Discover new PM tasks that are in CelloS scope.
6. Update task records, PM sync metadata, and attention metadata.
7. Evaluate tasks requiring attention.
8. Evaluate tasks that are ready for planning.
9. Evaluate approved executable tasks whose dependencies are satisfied.
10. Select a bounded set of tasks for this heartbeat.
11. Start worker tasks.
12. Record scheduling events and exit.

Background worker processes then:

1. Load configuration.
2. Open the local database.
3. Run the ACP worker for one task.
4. Save planning or execution results.
5. Record failures, change requests, and task events.
6. Push state and result updates back to PM tools when adapters exist.

Each background agent run creates a `task_attempts` record. The attempt captures the selected agent, connector, mode, prompt snapshot, result/error summary, and worker log path.

## Selection Rules

The heartbeat should not spawn an LLM session merely because a task exists.

Do not process a task just because:

- it remains in a planning list,
- it remains approved but blocked,
- it is waiting for a human,
- CelloS was the last actor and nothing changed.

An LLM session requires one of:

- durable attention metadata requiring AI action,
- a draft task that needs an initial plan,
- approved executable work,
- stale/hung task handling that requires reasoning,
- explicit user command to reprocess or check.

## Planning Mode

Planning and execution are distinct scheduler modes.

Planning is allowed for:

- `draft` tasks, and
- `needs_approval` tasks that have new attention, such as a human revision comment.

Planning workers may draft or revise the task prompt/plan. A successful planning result leaves the task in:

```text
needs_approval
```

Planning does not mark the task `done`, and it does not authorize execution. The human must approve the resulting prompt/scope before `cellos run` schedules execution.

Execution is allowed for:

- `approved` tasks whose dependencies are satisfied.

Execution workers perform the approved work and then save a normal result, failure, or change request.

Human comments are stored separately from the task prompt/plan. A comment on an unapproved task marks durable attention, which makes the task eligible for replanning without adding a separate revision status. Planning prompts include task comments and research-result system comments. Execution prompts stay focused on the approved plan.

## Concurrency

The scheduler has a bounded concurrency setting:

```text
concurrent_tasks = 4
```

This limits worker tasks started in one heartbeat. It does not require a long-running queue service for the MVP.

## Result Handling

When a worker finishes, CelloS records:

- task result,
- summary,
- success/failure,
- change request if applicable,
- timestamps,
- task events,
- PM update payloads.

If PM update push fails after local state is recorded, the next heartbeat should be able to retry the PM sync.

## See Also

- `cellos/services/scheduler.py` — `SchedulerService.run_once()` implementation
- `cellos/services/worker_service.py` — worker runtime
- `cellos/services/worker_spawner.py` — subprocess spawning
- `docs/architecture.md` — runtime flows and module responsibilities
- `docs/roles-and-lifecycle.md` — task lifecycle and attention signals
