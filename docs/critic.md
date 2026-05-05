# CelloS Refactoring Plan

## The Core Problem

`cli.py` is 769 lines doing everything. It's not just CLI parsing — it contains:
- Database operations (tasks, events, comments, attempts)
- Task lifecycle logic (approval, status transitions, dependency resolution)
- Scheduler heartbeat logic (attention queue, planning queue, execution queue)
- Worker spawning (subprocess management)
- Planning result parsing → child task creation
- Execution result parsing → dependency wiring → parent blocking

That file is the single biggest blocker. An LLM can't reliably change anything in it without understanding the entire file's interdependencies.

## Other Pain Points

| File | Lines | Problem |
|---|---|---|
| `cli.py` | 769 | Everything. See above. |
| `db.py` | 575 | Every CRUD op, every query, every business rule about dependencies — all in one file with embedded SQL |
| `models.py` | 194 | 15+ types crammed together — enums, metadata DTOs, domain entities, all mixed |
| `config.py` | 189 | Loading, path resolution, example file copying, validation — all in one function chain |

## The Architectural Mismatch

`cellos worker` runs as a **separate subprocess** (line 759 in `cli.py`). But all the business logic lives in `cli.py`, which means:
1. The subprocess imports from the CLI module — conceptually wrong
2. The CLI module is bloated because it needs to serve both the interactive CLI and the background worker process
3. There's no clear boundary between "what the CLI does" and "what the worker does"

## Proposed Structure

```
cellos/
├── cli/                    # Thin CLI layer only
│   ├── main.py            # click.group, command decorators
│   ├── commands/
│   │   ├── init.py        # init command
│   │   ├── add_task.py    # add-task
│   │   ├── run.py         # run (delegates to Scheduler)
│   │   ├── approve.py     # approve (delegates to TaskService)
│   │   ├── status.py      # status
│   │   ├── detail.py      # detail
│   │   ├── events.py      # events
│   │   ├── comment.py     # comment
│   │   ├── update.py      # update
│   │   └── worker.py      # worker entry point (thin — delegates to WorkerRunner)
│   └── formatting.py      # rich table rendering
├── services/               # Business logic — no CLI, no DB
│   ├── scheduler.py       # heartbeat: pick attention → planning → execution tasks
│   ├── task_service.py    # create, update, approve, dependency management
│   ├── worker_runner.py   # spawn worker subprocess, manage timeouts
│   ├── planning.py        # parse planning results → save to DB
│   └── execution.py       # parse execution results → create children, block parents
├── domain/                 # Domain models — no infrastructure
│   ├── models.py          # Task, TaskStatus, AgentRole, TaskType (lean)
│   ├── results.py         # TaskResult, TaskAttempt, TaskComment, ChangeRequestReport
│   └── attention.py       # AttentionMetadata, AttentionReason
├── infrastructure/         # Infrastructure concerns
│   ├── db/
│   │   ├── engine.py      # connection, init, close
│   │   ├── task_repo.py   # task CRUD + queries
│   │   ├── event_repo.py  # events, comments
│   │   └── attempt_repo.py # attempts
│   ├── config/
│   │   ├── loader.py      # load config from JSON
│   │   ├── models.py      # CellosConfig, AgentConfig, etc.
│   │   └── init.py        # ensure_config, example file copying
│   ├── prompts/
│   │   ├── builder.py     # build_task_prompt
│   │   └── profiles.py    # PromptProfilesConfig
│   └── agents/
│       ├── acp_worker.py  # AcpWorker (keep as-is, it's already fine)
│       └── connectors/    # opencode, fake_acp
└── task_actions.py        # Keep as-is (118 lines, well-scoped)
```

## Key Design Decisions

1. **Services talk to repos, not directly to DB** — `task_service.py` calls `task_repo.py`, which wraps `db.py`. This means you can swap DBs or mock repos for testing without touching business logic.

2. **Worker subprocess is a thin entry point** — `cellos worker` just loads config, opens DB, calls `WorkerRunner.run(task)`, saves result, exits. No CLI code, no scheduling logic.

3. **Scheduler is pure logic** — `cellos run` loads config, opens DB, calls `scheduler.run()`, which returns a plan. The CLI just prints it. The scheduler doesn't know about click or rich.

4. **Domain models are dumb** — no DB methods, no config references, no CLI. Just Pydantic models with validation.

5. **`task_actions.py` stays** — 118 lines, well-scoped, no problems.

## Refactoring Phases

**Phase 1: Extract services from cli.py** (biggest bang)
- Create `services/scheduler.py` from the `_run()` function
- Create `services/task_service.py` from `_add_task`, `_update`, `_approve`, `_comment`
- Create `services/planning.py` from `_save_planning_result`
- Create `services/execution.py` from `_save_execution_result`
- Create `services/worker_runner.py` from `_spawn_worker` + `_worker`
- Thin `cli.py` to just command decorators that call services

**Phase 2: Split the database**
- Split `db.py` into `engine.py`, `task_repo.py`, `event_repo.py`, `attempt_repo.py`
- Each repo is ~50-80 lines, focused on one entity

**Phase 3: Split models and config**
- Split `models.py` into domain entities vs. DTOs
- Split `config.py` into loader vs. config models

## What This Gets You

- No file over ~200 lines
- Clear "which file do I edit?" answers
- Services are testable in isolation (no click, no aiosqlite)
- Worker subprocess is a clean, self-contained entry point
- LLM can reason about `services/scheduler.py` without understanding CLI rendering or DB schema
