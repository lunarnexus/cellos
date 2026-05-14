# CelloS Architecture

## Source-of-Truth Docs

| Doc | What it covers |
|---|---|
| `roles-and-lifecycle.md` | Canonical roles, task lifecycle, approval model, attention signals |
| `acp.md` | Agent execution via ACP-compatible backends |
| `prompting.md` | Prompt stack, planning/execution boundaries, structured task creation |
| `communication.md` | Proposals, reports, approval requests, comments |
| `pm-adapters.md` | PM-neutral adapter contract |
| `trello.md` | Trello-specific mapping |
| `refactoring-spec.md` | Structural refactor plan and service contracts |

## Runtime Flows

### `cellos run` (scheduler heartbeat)

```
CLI command -> CellosApp bootstrap -> SchedulerService.run_once()
  -> select attention → planning → execution work
  -> mark scheduled tasks in_progress
  -> record scheduling events
  -> WorkerSpawner starts background worker processes
  -> CLI prints scheduled work and exits
```

### `cellos worker TASK_ID --mode planning|execution`

```
CLI command -> CellosApp bootstrap -> WorkerService.run_task_worker()
  -> load task/config/comments
  -> build prompt -> create task_attempt -> call backend
  -> PlanningService or ExecutionService saves result
  -> complete task_attempt -> record events -> close DB
```

## Module Responsibilities

| Change needed | Target module |
|---|---|
| CLI flags/output | `cellos/cli.py` |
| App bootstrap / path resolution | `cellos/cli_app.py` |
| Rich table rendering | `cellos/cli_formatting.py` |
| Scheduler / heartbeat logic | `cellos/services/scheduler.py` |
| Task create/update/comment/approve | `cellos/services/task_service.py` |
| Worker subprocess spawning | `cellos/services/worker_spawner.py` |
| Worker attempts / prompt / backend runtime | `cellos/services/worker_service.py` |
| Worker agent selection | `cellos/services/worker_service.py` + `cellos/config.py` |
| Planning result handling | `cellos/services/planning_service.py` |
| Execution result / child tasks | `cellos/services/execution_service.py` |
| SQL and persistence | `cellos/db.py` facade → `cellos/persistence/` repos |
| Domain DTOs / enums | `cellos/models.py` (canonical monolithic schema/types module) |
| Config loading / init | `cellos/config.py` (canonical monolithic config module) |
| Prompt construction | `cellos/prompt_builder.py` |
| Task action parsing | `cellos/task_actions.py` |
| ACP agent execution | `cellos/acp.py`, `cellos/acp_worker.py` |
| Agent connectors | `cellos/connectors/` |

## Where Do I Change X?

- **Scheduling rules?** → `cellos/services/scheduler.py` + `docs/refactoring-spec.md`
- **Task lifecycle / approval?** → `cellos/services/task_service.py` + `docs/roles-and-lifecycle.md`
- **Worker backend / prompt?** → `cellos/services/worker_service.py` + `cellos/prompt_builder.py`
- **CLI output format?** → `cellos/cli_formatting.py`
- **DB schema / queries?** → `cellos/persistence/` repos (facade in `cellos/db.py`)
- **Config structure?** → `cellos/config.py`
- **Schema/types?** → `cellos/models.py`
- **Agent connector?** → `cellos/connectors/<name>.py`

## Task-Specific Agents

Tasks can optionally specify an ACP agent from `agentcatalog.json`.

```bash
cellos add-task "Refactor CLI" --agent qwen
cellos update TASK_ID --agent claude
cellos update TASK_ID --clear-agent
```

- If `agent_id` is unset on a task, the worker uses `agents.default` from config (current behavior).
- If `agent_id` is set, `WorkerService` resolves that agent from `agentcatalog.json` and uses it for ACP execution and attempt records.
- Invalid agent IDs are rejected at task creation/update with a clear error.

### How it works

1. `Task` model carries an optional `agent_id: str | None`.
2. `CellosConfig.get_agent(agent_id)` resolves the agent: if `None` it returns the default; if set it looks up the catalog entry.
3. `WorkerService.run_task_worker()` calls `config.get_agent(task.agent_id)` to get the agent for the attempt record and ACP backend.
4. `TaskService.update_task()` accepts `agent_id` and `clear_agent` parameters.
5. `cli_formatting.py` detail view shows the task-specific agent if present.

### Where to change

- **Task model field** → `cellos/models.py`
- **Agent resolution** → `cellos/config.py` (`get_agent`)
- **CLI flags** → `cellos/cli.py` (`add-task`, `update`)
- **Service validation** → `cellos/services/task_service.py`
- **Worker execution** → `cellos/services/worker_service.py`
- **Display** → `cellos/cli_formatting.py`

## Known Open Questions

- Should `attention_required` be cleared before a worker starts, after local success, or only after PM sync succeeds?
- How should dependency completion create attention for downstream tasks?
- How should child `change_requested` tasks create attention for parent tasks?
- Should one heartbeat prioritize planning/revision work before execution work?
- What worker timeout and stale-task rules are safe for long-running tasks?
- How should attention signals be stored?
- How does the heartbeat avoid reprocessing the same task when no human or dependency state changed?
