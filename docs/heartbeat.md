# Heartbeat Loop

`cellos run` is one bounded scheduler heartbeat. It should be safe to run repeatedly from a CLI command, cron job, launchd job, systemd timer, webhook handler, or future daemon.

The heartbeat does not run forever. It performs one scan/sync/evaluation/execution pass, records state, then exits.

## Goals

- Keep each run cheap when nothing changed.
- Avoid spawning LLM workers unless a task has a new reason for attention or approved executable work.
- Continue independent work when one integration or task fails.
- Make repeated invocations safe and predictable.
- Treat project-management tools as interfaces, not as the source of orchestration truth.

## Configuration

The heartbeat reads configuration at the start of every run.

User config location:

```text
~/.cellos/config.json
```

The project ships a sample config:

```text
cellos.config.example.json
```

Initial sample config:

```json
{
  "scheduler": {
    "concurrent_tasks": 4,
    "worker_timeout_seconds": 300
  },
  "worker": {
    "backend": "acp",
    "command": ["python3", "-m", "cellos.connectors.fake_acp"],
    "debug_log_path": ".cellos/logs/acp-debug.log"
  }
}
```

Reading this small file every heartbeat is acceptable and useful. Config changes take effect on the next `cellos run`. CLI flags may override config values for one heartbeat.

PM authentication, auto-approval, and provider-specific settings are intentionally deferred to their own design sections.

## Best Effort

The heartbeat should be best-effort.

If one adapter, task, or worker fails, CelloS should:

- record the error,
- continue independent work where possible,
- avoid crashing the whole heartbeat unless local state cannot be handled safely.

Examples:

- If PM sync fails, local-only tasks may still run.
- If one worker task fails, other selected tasks may still complete.
- If config is partially missing, CelloS should use defaults where safe and report what could not be loaded.

## Polling First

Assume the worst case: project-management tools may not reliably notify CelloS about every edit.

Some tools support webhooks, but they can fail, be delayed, or require setup. Therefore the core design must work by polling:

```text
heartbeat polls PM state -> detects changes -> updates local CelloS state
```

Webhooks can later trigger heartbeats sooner, but polling remains the baseline.

## Sync And Evaluation

The heartbeat has two distinct phases:

### Sync

Sync reads external state and updates local state.

Responsibilities:

- Read known PM-linked tasks.
- Discover new in-scope PM tasks.
- Detect human edits, comments, moves, approvals, cancellations, and relationship changes.
- Update local task records and PM sync metadata.
- Mark durable attention metadata when something requires CelloS action.

### Evaluation

Evaluation decides what CelloS should do with local state.

Responsibilities:

- Inspect tasks with `attention_required`.
- Inspect approved executable tasks whose dependencies are satisfied.
- Decide whether to plan, revise, create tasks, execute work, test work, or report status.
- Select a bounded amount of work for the current heartbeat.

In short:

```text
sync notices what changed
evaluation decides what to do
```

## Attention Metadata

Task status and task attention are separate.

Status answers:

```text
Where is this task in its lifecycle?
```

Attention answers:

```text
Should CelloS inspect or act on this task?
```

Attention is stored as durable task metadata. See `roles-and-lifecycle.md` for the canonical attention model.

Common attention reasons:

```text
new_task
human_changed_task
human_commented
approved
dependency_done
child_change_requested
stale_in_progress
external_state_changed
```

## Processing Metadata

Each task should store enough metadata to avoid repeated work.

Useful fields:

```text
last_processed_at
last_human_change_at
last_ai_change_at
last_observed_external_change_at
last_processed_external_change_at
last_processed_input_hash
```

Meaning:

- `last_processed_at`: when CelloS last acted on the task.
- `last_human_change_at`: when a human last edited, commented, or moved the task meaningfully.
- `last_ai_change_at`: when CelloS last edited, commented, or moved the task.
- `last_observed_external_change_at`: newest relevant timestamp seen in the PM tool.
- `last_processed_external_change_at`: newest PM change CelloS has already handled.
- `last_processed_input_hash`: hash of the content/scope CelloS last processed.

These can live in the task model and PM sync metadata.

## Heartbeat Order

One heartbeat should run in this order:

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

Known PM-linked tasks should be synced before discovering new candidates. Active workflows should keep moving before new work is imported.

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

## Open Questions

- Should `attention_required` be cleared before a worker starts, after local success, or only after PM sync succeeds?
- How should dependency completion create attention for downstream tasks?
- How should child `change_requested` tasks create attention for parent tasks?
- Should one heartbeat prioritize planning/revision work before execution work?
- What worker timeout and stale-task rules are safe for long-running tasks?
