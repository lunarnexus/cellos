# CelloS Refactoring Spec

## Status

Phase 0 architecture spec. Phases 1-7 are complete. This document is the working source of truth for the structural refactor until superseded.

## Intent

CelloS currently works only at a rudimentary level. This refactor is allowed to improve behavior where the existing design is weak, not merely preserve behavior byte-for-byte.

The main goal is to make the project small-context friendly: each future task should have an obvious module boundary, an obvious test boundary, and a small enough implementation surface that an LLM or human can work without loading half the codebase.

## Current Problems

The current architecture concentrates too much behavior in a few files:

| File | Approx. lines | Problem |
|---|---:|---|
| `cellos/cli.py` | 334 | CLI parsing, rendering, app bootstrap (was 769; logic extracted to services/) |
| `cellos/db.py` | 184 | Thin facade delegating to `persistence/` repos |
| `cellos/persistence/` | ~600 | 7 focused repository modules (split from db.py in Phase 8) |
| `cellos/models.py` | 194 | enums, task models, result DTOs, attempt DTOs, comments, attention metadata |
| `cellos/config.py` | 189 | config models, loading, path resolution, initialization/copying |

The biggest mismatch: `cellos run` and `cellos worker` are CLI commands, but their core behavior is not CLI behavior. The CLI should parse arguments and render output. It should not own scheduling, attempts, worker process lifecycle, task lifecycle rules, or result interpretation.

## Design Principles

1. **Services own orchestration behavior.** Scheduler, task lifecycle, planning result handling, execution result handling, and worker runtime belong in service modules.
2. **CLI stays thin.** Click commands should parse arguments, call services, and render output.
3. **Persistence is behind repositories/facades.** Services should not depend on raw SQL details long-term.
4. **Behavior may improve.** This is not a strict compatibility refactor. Preserve useful existing behavior, but fix obviously weak behavior when it reduces future complexity.
5. **Phase gates matter.** Each phase should be independently testable and should end with tests passing.
6. **Compatibility shims are allowed.** Avoid dangerous import/package renames until service boundaries are stable.
7. **No task explosion.** Split by responsibility, not by creating dozens of tiny files with vague names.
8. **Docs become navigational, not archival.** Keep canonical docs concise and point to the right module for each responsibility.

## Canonical Runtime Flow

Target runtime flow:

```text
cellos CLI command
  -> app bootstrap opens config + DB
  -> command-specific service
  -> DB facade/repository
  -> service result DTO
  -> CLI formatter renders output
```

Heartbeat flow:

```text
cellos run
  -> SchedulerService.run_once()
  -> select planning / attention / execution work
  -> mark scheduled tasks in_progress
  -> record scheduling events
  -> WorkerSpawner starts background worker process
  -> CLI prints scheduled work and exits
```

Worker flow:

```text
cellos worker TASK_ID --mode planning|execution
  -> WorkerService.run_task_worker()
  -> load task/config/comments as needed
  -> build prompt
  -> create task_attempt
  -> call configured worker backend
  -> PlanningService or ExecutionService saves result
  -> complete task_attempt
  -> close DB
```

## Target Module Layout

Current state (after Phases 1-8):

```text
cellos/
├── cli.py                    # thin CLI entry point (334 lines, was 769)
├── cli_app.py                # app bootstrap, path resolution, async runner helpers
├── cli_formatting.py         # Rich rendering only
│
├── services/
│   ├── __init__.py
│   ├── scheduler.py          # one-turn scheduler service
│   ├── task_service.py       # add/update/comment/approve lifecycle behavior
│   ├── worker_service.py     # background worker runtime and attempts
│   ├── worker_spawner.py     # subprocess spawning only
│   ├── planning_service.py   # save planning result
│   └── execution_service.py  # save execution result, child task creation, parent blocking
│
├── persistence/              # Phase 8: split from db.py
│   ├── __init__.py           # exports REQUIRED_TABLES, DatabaseNotInitialized
│   ├── schema.py             # REQUIRED_TABLES, DatabaseNotInitialized, init_db, ensure_initialized
│   ├── serialization.py      # json_payload, task_row, attempt_row
│   ├── event_repository.py   # record_task_event, list_task_events
│   ├── comment_repository.py # add_task_comment, list_task_comments
│   ├── attempt_repository.py # start_task_attempt, complete_task_attempt, list_task_attempts
│   ├── result_repository.py  # save_task_result, dependency wake logic
│   └── task_repository.py    # task CRUD, status updates, list queries
│
├── db.py                     # thin facade delegating to persistence/ repos (184 lines, was 575)
├── models.py                 # canonical monolithic schema/types module
├── config.py                 # canonical monolithic config module
├── prompt_builder.py         # already focused
├── task_actions.py           # already focused
├── acp_worker.py             # already focused
└── connectors/               # already focused
```

`heartbeat.py` and `workers.py` have been deleted (stale/unused).

Later, after behavior is stable, consider a cleaner package migration:

```text
cellos/cli/
├── __init__.py
├── main.py
├── app.py
├── options.py
├── formatting.py
└── commands/
    ├── init.py
    ├── add_task.py
    ├── status.py
    ├── detail.py
    ├── events.py
    ├── update.py
    ├── comment.py
    ├── approve.py
    ├── run.py
    └── worker.py
```

Only do this once service extraction is complete, because it requires coordinated updates to imports, `pyproject.toml`, tests, and subprocess commands.

## Service Contracts

### `SchedulerService`

Module: `cellos/services/scheduler.py`

Purpose: own one bounded scheduler heartbeat.

Suggested DTO:

```python
@dataclass(frozen=True)
class ScheduleResult:
    attention_tasks: list[Task]
    planning_tasks: list[Task]
    execution_tasks: list[Task]
```

Suggested API:

```python
class SchedulerService:
    async def run_once(self, concurrent_tasks: int | None = None) -> ScheduleResult:
        ...
```

Responsibilities:

- load scheduling capacity from explicit argument or config,
- select planning candidates,
- select attention tasks,
- select approved unblocked execution tasks,
- reserve capacity across those queues,
- mark scheduled planning/execution tasks `in_progress`,
- record scheduling events,
- ask `WorkerSpawner` to start background workers,
- return a concise schedule result for CLI rendering.

Behavior improvements allowed:

- make prioritization explicit and documented,
- avoid scheduling a task twice in one heartbeat,
- record clearer scheduling/failure events,
- handle worker spawn failure as a recorded task failure/change rather than crashing the whole heartbeat.

### `WorkerSpawner`

Module: `cellos/services/worker_spawner.py`

Purpose: own subprocess construction and launch only.

Suggested API:

```python
class WorkerSpawner:
    def spawn(
        self,
        task: Task,
        *,
        mode: Literal["planning", "execution"],
        db_path: Path,
        config_path: Path,
        workdir: Path,
    ) -> None:
        ...
```

Responsibilities:

- construct the worker command,
- create worker log directory,
- redirect stdout/stderr to the worker log,
- start detached process safely,
- avoid knowing scheduling rules or result handling.

Compatibility rule:

Keep this command initially:

```text
python -m cellos.cli worker TASK_ID --mode MODE ...
```

Do not change subprocess entrypoint until the service extraction is stable.

### `WorkerService`

Module: `cellos/services/worker_service.py`

Purpose: own the actual background worker runtime.

Suggested API:

```python
class WorkerService:
    async def run_task_worker(self, task_id: str, mode: Literal["planning", "execution"]) -> None:
        ...
```

Responsibilities:

- load task,
- load comments for planning mode,
- build prompt,
- create task attempt,
- create configured backend worker,
- run backend,
- catch backend failures into `TaskResult`,
- delegate successful/failed result persistence to planning/execution services,
- complete task attempt,
- record worker events.

Behavior improvements allowed:

- always complete attempts, including unexpected persistence failures when possible,
- record error details consistently,
- keep raw output/error information for debugging,
- make mode validation explicit.

### `PlanningService`

Module: `cellos/services/planning_service.py`

Purpose: own planning result persistence.

Suggested API:

```python
class PlanningService:
    async def save_result(self, task: Task, result: TaskResult) -> Task:
        ...
```

Responsibilities:

- save worker output as the proposed prompt/plan,
- clear attention when planning handles it,
- set status to `needs_approval` on successful planning,
- preserve failed planning as failure or change request according to lifecycle rules,
- record `planning_saved` or failure events.

Behavior improvements allowed:

- distinguish a successful plan from a failed planning attempt more clearly,
- avoid overwriting useful prior prompt text without keeping result history,
- make failed planning status explicit.

### `ExecutionService`

Module: `cellos/services/execution_service.py`

Purpose: own execution result persistence and child-task effects.

Suggested API:

```python
class ExecutionService:
    async def save_result(self, task: Task, result: TaskResult) -> Task:
        ...
```

Responsibilities:

- save execution result,
- parse structured task creation actions,
- record invalid task action events,
- create child tasks when allowed,
- enforce approval requirements for research, engineer, and tester child tasks,
- block parent on blocking child tasks,
- record child creation and parent blocking events.

Behavior improvements allowed:

- enforce task creation policy more explicitly,
- separate invalid structured actions from worker failure,
- support change-request results without abusing generic failure.

### `TaskService`

Module: `cellos/services/task_service.py`

Purpose: own human/task lifecycle operations that are currently buried in CLI helpers.

Suggested API:

```python
class TaskService:
    async def create_task(self, task: Task) -> Task:
        ...

    async def update_task(... ) -> Task:
        ...

    async def add_human_comment(self, task_id: str, message: str, author_id: str) -> None:
        ...

    async def approve_task(self, task_id: str) -> Task:
        ...
```

Responsibilities:

- create tasks,
|- update title/prompt/status/parent/dependencies,
- mark attention for human edits/comments when appropriate,
- record lifecycle events,
- approve tasks,
- clear attention on approval.

Behavior improvements allowed:

- normalize validation errors into service-level exceptions,
- require clearer approval transitions,
- make relationship updates and content updates easier to test independently.

## CLI Responsibilities

The CLI may own:

- Click decorators,
- argument parsing,
- shell-friendly error conversion,
- output formatting calls,
- command registration.

The CLI must not own:

- scheduling rules,
- task lifecycle rules,
- worker backend construction beyond delegating to services,
- result persistence rules,
- child task creation rules,
- database query details.

## Persistence Refactor Complete (Phase 8)

Phase 8 is done. `db.py` is now a 184-line facade delegating to `cellos/persistence/` repositories.

Future target (after behavior is stable):

```text
cellos/infrastructure/db/
├── engine.py
├── task_repo.py
├── event_repo.py
├── comment_repo.py
└── attempt_repo.py
```

The current `cellos/persistence/` layout is the stable repository boundary. Only consider restructuring into `infrastructure/db/` if a clear benefit emerges.

## Model and Config State (Phase 9 decision)

Phase 9 is considered complete with a revised outcome:

- `models.py` remains the canonical monolithic home for schema/types.
- `config.py` remains the canonical monolithic home for configuration.
- `cellos/domain/*` remains only as a compatibility shim layer for existing imports.

This keeps the type surface small-context friendly without spreading simple schema
data across many files.

## Documentation Cleanup Target

Phase 10 completed. Created `docs/architecture.md` as the navigation doc.

It includes:

- source-of-truth docs,
- runtime flow,
- module responsibility table,
- “where do I change X?” table,
- known open questions.

Recommended table:

| Change needed | Target module |
|---|---|
| CLI flags/output | `cellos/cli.py`, later `cellos/cli/*` |
| app bootstrap/path resolution | `cellos/cli_app.py` |
| heartbeat scheduling / scheduler decisions | `cellos/services/scheduler.py` |
| task creation/update/comment/approval | `cellos/services/task_service.py` |
| worker subprocess spawning | `cellos/services/worker_spawner.py` |
| worker attempts/prompt/backend runtime | `cellos/services/worker_service.py` |
| planning result handling | `cellos/services/planning_service.py` |
| execution result/child tasks | `cellos/services/execution_service.py` |
| SQL and persistence | `cellos/db.py`, later `cellos/infrastructure/db/*` |
| domain DTOs/enums | `cellos/models.py`, later `cellos/domain/*` |
| config loading/init | `cellos/config.py`, later split carefully |

## Implementation Phases

### Phase 1: Extract scheduler service

Status: implemented.

### Phase 2: Extract worker runtime service

Status: implemented.

### Phase 3: Extract planning and execution result services

Status: implemented.

### Phase 4: Extract task lifecycle service

Status: implemented.

### Phase 5: Extract CLI app helpers and formatting

Status: implemented.

### Phase 6: Decide CLI package migration + heartbeat cleanup

Status: implemented.

Decisions:
- `cellos/heartbeat.py` stays deleted. `SchedulerService` is the canonical implementation.
- CLI package migration deferred. Current flat layout (`cli.py` + `cli_app.py` + `cli_formatting.py`) is sufficient.
- No compatibility shim for `cellos/heartbeat.py` — no external code imports it.

### Phase 7: Delete stale files

Status: implemented.

Deleted:
- `cellos/heartbeat.py` (53 lines, stale abstraction superseded by `SchedulerService`)
- `cellos/workers.py` (16 lines, dead code)
- `tests/test_heartbeat.py` (139 lines, tests for deleted code)

### Phase 8: Split DB into repositories

Target:

```text
cellos/persistence/
├── __init__.py           # exports REQUIRED_TABLES, DatabaseNotInitialized
├── schema.py             # REQUIRED_TABLES, DatabaseNotInitialized, init_db, ensure_initialized
├── serialization.py      # json_payload, task_row, attempt_row
├── event_repository.py   # record_task_event, list_task_events
├── comment_repository.py # add_task_comment, list_task_comments
├── attempt_repository.py # start_task_attempt, complete_task_attempt, list_task_attempts
└── task_repository.py    # task CRUD, status updates, list queries
```

Keep `CellosDatabase` facade during transition. Services call `CellosDatabase` methods; those delegate to repository functions.

#### Phase 8A: Schema extraction

Status: implemented.

Created `cellos/persistence/schema.py`. Moved `REQUIRED_TABLES`, `DatabaseNotInitialized`, `init_db`, `ensure_initialized`.

#### Phase 8B: Serialization helpers

Status: implemented.

Created `cellos/persistence/serialization.py`. Moved `json_payload`, `task_row`, `attempt_row`.

#### Phase 8C: Event/comment/attempt repositories

Status: implemented.

Created:
- `cellos/persistence/event_repository.py`
- `cellos/persistence/comment_repository.py`
- `cellos/persistence/attempt_repository.py`

Moved implementation of `record_task_event`, `list_task_events`, `add_task_comment`, `list_task_comments`, `start_task_attempt`, `complete_task_attempt`, `list_task_attempts`.

`CellosDatabase` methods delegate to these functions.

Test gate:

```bash
python3 -m pytest tests/test_db.py tests/test_worker_service.py tests/test_scheduler_service.py -q
python3 -m pytest -q
```

#### Phase 8D: Task CRUD/query extraction

Status: implemented.

Created `cellos/persistence/task_repository.py`. Moved `create_task`, `update_task`, `get_task`, `list_tasks`, `list_tasks_requiring_attention`, `list_tasks_ready_for_planning`, `list_approved_unblocked_tasks`, `list_tasks_depending_on`, `dependencies_satisfied`, `update_task_status`, `_replace_dependencies`, `_fetchone`. `CellosDatabase` methods delegate.

Test gate:

```bash
python3 -m pytest tests/test_db.py tests/test_task_service.py tests/test_scheduler_service.py -q
python3 -m pytest -q
```

#### Phase 8E: Result persistence extraction

Status: implemented.

Created `cellos/persistence/result_repository.py`. Moved `save_task_result`, `_wake_satisfied_blocked_dependents`, `_add_dependency_result_comments`. Repo functions accept `database` instance directly (not callback functions). `CellosDatabase` methods delegate.

Test gate:

```bash
python3 -m pytest tests/test_db.py tests/test_worker_service.py tests/test_scheduler_service.py -q
python3 -m pytest -q
```

### Phase 9: Re-evaluate models/config structure

Status: implemented.

#### Phase 9A: Domain split evaluated, then collapsed back to monolithic models (implemented)

Final structure:

```text
cellos/
  models.py                    # canonical monolithic schema/types module
  domain/
    __init__.py
    time.py                    # compatibility shim
    enums.py                   # compatibility shim
    attention.py               # compatibility shim
    results.py                 # compatibility shim
    comments.py                # compatibility shim
    attempts.py                # compatibility shim
    tasks.py                   # compatibility shim
    workers.py                 # compatibility shim
```

Decision: the split domain files added indirection without enough benefit. `models.py`
is small and cohesive enough to remain the canonical home for schema/types.

Test gate passed:

```bash
python3 -m pytest tests/test_models.py -q
python3 -m pytest -q
```

#### Phase 9B: Keep configuration monolithic (implemented decision)

Decision: keep `cellos/config.py` as one file. Prompts already live in external JSON files. Splitting config into multiple Python modules adds cognitive overhead without meaningful benefit — someone needs to open multiple files to understand how config works, and the file is only 189 lines.

Future: if `cellos/config.py` grows past ~300 lines, reconsider. Until then, it stays monolithic.

#### Phase 9C: Migrate production imports to `cellos.models` (implemented)

Updated 19 production source files to import from `cellos.models` instead of `cellos.domain.*`. Config imports unchanged (9B skipped).

Files updated:

```text
cellos/task_actions.py
cellos/cli_formatting.py
cellos/acp_worker.py
cellos/cli.py
cellos/pm.py
cellos/services/worker_spawner.py
cellos/persistence/event_repository.py
cellos/services/scheduler.py
cellos/services/execution_service.py
cellos/persistence/attempt_repository.py
cellos/services/planning_service.py
cellos/services/worker_service.py
cellos/persistence/task_repository.py
cellos/services/task_service.py
cellos/persistence/comment_repository.py
cellos/persistence/serialization.py
cellos/db.py
cellos/prompt_builder.py
cellos/persistence/result_repository.py
```

Import mapping:

```text
AgentRole, TaskStatus, TaskType, AttentionReason, CommentAuthorType
  → cellos.models

Task, TaskDependency
  → cellos.models

TaskResult, ChangeRequestReport
  → cellos.models

TaskComment
  → cellos.models

TaskAttempt, TaskAttemptStatus
  → cellos.models

utc_now
  → cellos.models
```

`cellos/domain/*` remains as a compatibility shim layer re-exporting from `cellos.models`. Tests may import from either location, but `cellos.models` is canonical.

Test gate:

```bash
python3 -m pytest -q
72 passed
```

Zero production files need to import from `cellos.domain.*` after this phase.

#### Phase 9D: Keep domain imports only as compatibility shims in tests where useful (implemented)

Updated 9 test files to import from `cellos.models` as the canonical source. Kept a narrow compatibility check to verify `cellos.domain.*` shims still resolve correctly.

Files updated:

```text
tests/test_models.py
tests/test_db.py
tests/test_pm.py
tests/test_acp_worker.py
tests/test_task_service.py
tests/test_task_actions.py
tests/test_scheduler_service.py
tests/test_worker_service.py
```

Config tests unchanged (9B skipped — config stays monolithic):

```text
tests/test_config.py  — still imports from cellos.config (compatibility test added)
```

Compatibility tests added:

- `tests/test_models.py::test_domain_compatibility_exports_still_work` — verifies compatibility shim imports still resolve
- `tests/test_config.py::test_config_compatibility_exports` — verifies all 5 config functions exportable from `cellos.config`

Test gate:

```bash
python3 -m pytest -q
74 passed
```

### Phase 10: Docs cleanup

Status: implemented.

#### Phase 10A: Trim verbose docs

Reduced total docs from 2,578 to 1,885 lines (-693 lines, -27%).

Changes:

- Removed stale `docs/heartbeat.md`. Scheduler behavior now lives in `docs/architecture.md`, `docs/roles-and-lifecycle.md`, `docs/acp.md`, and the service-oriented runtime notes in this spec.
- `docs/roles-and-lifecycle.md`: 332 → 194 lines. Condensed role descriptions, added status table, streamlined change request flow.
- `docs/acp.md`: 204 → 95 lines. Removed verbose config examples, kept: ACP architecture, connector model, agent catalog, runtime behavior.
- `docs/communication.md`: 155 → 92 lines. Trimmed verbose artifact format examples, kept: artifact types, proposal structure, change request format.
- `docs/prompting.md`: 138 → 85 lines. Trimmed verbose planning mode rules, kept: prompt stack order, planning vs execution boundaries.
- `docs/pm-adapters.md`: 139 → 58 lines. Trimmed verbose responsibility lists, kept: adapter contract, canonical concepts.
- `docs/trello.md`: 175 → 84 lines. Trimmed verbose list mapping, kept: Trello concepts, in-scope cards, lists, labels, cards, sync behavior.

#### Phase 10B: Update stale docs

- `docs/implementation-plan.md`: Updated to reflect completed refactoring (Phases 8-9 done, 74 tests passing).
- `smoketest.md`: Updated test count (74, not 72), updated `cellos run` description to reference `SchedulerService.run_once()`.

#### Phase 10C: Navigation docs (completed in prior phases)

- `docs/architecture.md` — navigation doc with module responsibility table and runtime flows.
- `docs/README.md` — canonical docs list, core decisions, working rule.
- `docs/archive/critic.md` — archived (superseded by `refactoring-spec.md`).

#### Phase 10D: Unchanged

- `docs/product.md` (79 lines) — product vision, kept as-is.
- `docs/refactoring-spec.md` — structural refactor plan, updated to reflect the final monolithic `models.py` decision.

Test gate:

```bash
python3 -m pytest -q
74 passed
```

## Open Design Decisions

1. Should failed planning set task status to `failed`, return it to `draft`, or produce `change_requested`?
2. Should `execution_service` enforce task-creation authorization based only on config, or inspect approved prompt text for explicit authorization?
3. Should worker subprocesses remain `python -m cellos.cli worker` permanently, or move to a dedicated non-CLI worker entrypoint?
4. Should app bootstrap live in `cli_app.py` or in a neutral `runtime.py` module?
5. How aggressive should the docs cleanup be after `docs/architecture.md` exists?

## Definition of Done for the Refactor

- `cellos/cli.py` is mostly Click command wiring and has no core business logic.
- Real scheduler behavior lives in `cellos/services/scheduler.py`.
- Worker runtime lives outside CLI.
- Planning and execution result handling live outside CLI.
- Task lifecycle rules live outside CLI.
- Tests pass after each phase.
- Future contributors can answer “which file do I edit?” without reading `cli.py` top to bottom.
- Documentation points to module ownership instead of repeating long design history everywhere.
