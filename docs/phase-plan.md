# CelloS Build Plan

## Phase Overview

Each phase is self-contained with clear acceptance criteria. Phases build on each other but can be tested independently via unit tests before integration testing in later phases.

**Build order rationale**: Foundation first (models, DB), then services, then CLI surface area, then ACP integration, then daemon/worker complexity, then polish and full test coverage.

---

## Phase 1: Project Scaffolding + Data Models
**Goal**: Package structure, pyproject.toml, all enums and Pydantic models with tests.

### Files to Create
```
cellos/
├── pyproject.toml              # Package metadata, deps (aiosqlite, pydantic>=2, click, rich)
├── README.md                   # Brief project description
└── cellos/
    ├── __init__.py             # Package marker + version
    └── models.py               # All enums + Pydantic models from data-model.md
```

### Dependencies
- `aiosqlite>=0.20` — async SQLite driver
- `pydantic>=2.0` — model validation and serialization  
- `click>=8.0` — CLI framework
- `rich` — formatted terminal output (tables, panels)
- Dev: `pytest`, `pytest-asyncio`

### pyproject.toml Entry Point
```toml
[project.scripts]
cellos = "cellos.cli:main"
```

### Acceptance Criteria
- [ ] All enums from data-model.md defined as StrEnum with correct values
- [ ] Task model has all fields including attention/processing metadata
- [ ] Backward-compat migration in model_validator (proposal→prompt_text, description→details)
- [ ] `requires_attention()` and `clear_attention()` return copies via model_copy
- [ ] All supporting models: AttentionMetadata, ProcessingMetadata, ConversationMessage, TaskComment, TaskResult, TaskAttempt, TaskEvent, Worker, TaskDependency
- [ ] Test file `tests/test_models.py` covers all enums, model construction, migrations, attention helpers (~18 tests)
- [ ] `pytest -q` passes

---

## Phase 2: Persistence Layer
**Goal**: SQLite schema, repositories, database facade. Full CRUD for tasks and supporting tables.

### Files to Create
```
cellos/
├── db.py                       # CellosDatabase async facade wrapping repos
└── persistence/
    ├── __init__.py
    ├── schema.py               # SQL DDL + init_db() + ensure_initialized()
    ├── task_repository.py      # Task CRUD + scheduler queries
    ├── result_repository.py    # Result saving + side effects (wake blocked dependents)
    ├── event_repository.py     # Event logging
    ├── comment_repository.py   # Comment storage
    └── attempt_repository.py   # Attempt tracking
```

### Key Design Decisions
- Function-based repositories (not classes). Each takes `aiosqlite.Connection` as first param.
- JSON columns for complex nested data (conversation, dependencies, attention, processing)
- Use `json_extract()` with partial index for attention queries — NOT LIKE on blobs
- Dependencies stored both inline (JSON in tasks table) and junction table (FK constraints)

### Acceptance Criteria
- [ ] Schema creates all 6 tables: tasks, task_dependencies, task_results, task_events, task_comments, task_attempts
- [ ] `init_db()` is idempotent (safe to call multiple times)
- [ ] TaskRepository: create_task, get_task, list_tasks, update_task, status queries
- [ ] Scheduler queries working: list_attention_tasks, list_planning_candidates, list_approved_unblocked
- [ ] Result saving triggers side effects: wake blocked dependents, add dependency result comments
- [ ] Event/comment/attempt repos handle CRUD correctly
- [ ] Test file `tests/test_persistence.py` covers all repos with real temp SQLite DBs (~20 tests)
- [ ] `pytest -q` passes

---

## Phase 3: Configuration System
**Goal**: Three-file config loading (config.json, agentcatalog.json, promptprofiles.json), Pydantic validation, example configs.

### Files to Create
```
cellos/
└── config.py                   # CellosConfig + all sub-configs + load_config() + ensure_config()
```

Plus example files at repo root:
- `cellos.config.json.example` — Main config with scheduler, worker, agents settings (copied to ~/.cellos/ on init)
- `agentcatalog.json.example` — 4 agents (architect/engineer/researcher/tester) using cellos_acp
- `promptprofiles.json.example` — Role instructions + mode sections for all roles

Config files live in `~/.cellos/` by default. The CLI accepts `--config-dir <path>` to point to a different config directory.

### Acceptance Criteria
- [ ] CellosConfig loads from three JSON files with Pydantic validation
- [ ] Path resolution: relative paths resolved against config dir, absolute used as-is  
- [ ] Agent catalog supports multiple agents with connector type selection
- [ ] Prompt profiles externalize ALL prompt content — no hardcoded strings elsewhere
- [ ] `preapprove_research_tasks` flag in config controls whether child research tasks auto-transition to APPROVED or stay at NEEDS_APPROVAL (default: false)
- [ ] `ensure_config()` copies example files for initialization
- [ ] Test file `tests/test_config.py` covers loading, validation errors, agent resolution (~9 tests)
- [ ] `pytest -q` passes

---

## Phase 4: Services Layer (TaskService + Planning/Execution)
**Goal**: Business logic services with state machine enforcement and attention tracking.

### Files to Create
```
cellos/services/
├── __init__.py
├── task_service.py             # CRUD, approval gates, comments, conversation, dependencies
├── planning_service.py         # Plan generation stub + save_planning_result()  
├── execution_service.py        # save_execution_result() (no structured actions yet)
```

### Key Design Decisions
- TaskService enforces state machine: can only approve NEEDS_APPROVAL tasks
- Attention auto-triggered on content changes for non-approved tasks
- Custom exceptions: TaskNotFoundError, EmptyTaskUpdateError, InvalidTaskApprovalError
- Planning/execution services are thin — they save results and update status

### Acceptance Criteria
- [ ] create_task generates ID, sets defaults, infers task_type from role
- [ ] approve_task enforces NEEDS_APPROVAL → APPROVED transition only
- [ ] Content changes trigger attention on draft/needs_approval tasks (not approved/done)
- [ ] Comments and conversation messages work with author type tracking
- [ ] Dependency add/remove logic works correctly  
- [ ] Planning service saves plan text + transitions to NEEDS_APPROVAL
- [ ] Execution service saves result + transitions to DONE or FAILED
- [ ] Test file `tests/test_services.py` covers full lifecycle (~18 tests)
- [ ] `pytest -q` passes

---

## Phase 5: CLI Foundation (init, add-task, status, detail, approve, comment, events, update)
**Goal**: Working Click CLI with Rich output for all manual task operations. No ACP integration yet — everything is local state manipulation.

### Files to Create
```
cellos/
└── cli.py                      # Click command group + all commands
```

### Commands
| Command | Description |
|---------|-------------|
| `init [--overwrite]` | Create config files in ~/.cellos/, init SQLite DB |
| `add-task <title> [-d details] [-r role] [-t type] [-s success_criteria] [-f failure_criteria] [--depends ids]` | Create task |
| `status [-s status_filter]` | Rich table of tasks with ⚠️ attention markers |
| `detail <task_id>` | Rich panel showing full task info including plan, conversation, comments |
| `approve <task_id>` | Approve a NEEDS_APPROVAL task (human gate) |
| `comment <task_id> -m message` | Add human comment + trigger attention if applicable |
| `events <task_id> [--limit N]` | Show audit trail events |
| `update <task_id> [options]` | Update any field: --title, --status, --add-dep, --remove-dep, etc. |

### Acceptance Criteria
- [ ] All 8 commands work end-to-end with real SQLite DB
- [ ] Rich tables for status (ID, Status bold, Role, Title + ⚠️)
- [ ] Rich panels for detail view  
- [ ] Error messages are clear and actionable (e.g., "Cannot approve task in 'draft' status")
- [ ] `--db` and `--config` global options propagate to all subcommands
- [ ] Test file `tests/test_cli.py` covers all commands with CliRunner (~14 tests)
- [ ] Manual smoke test: init → add-task → status → detail → comment → approve → events works
- [ ] `pytest -q` passes

---

## Phase 6: ACP Integration + Connectors
**Goal**: Protocol-based connectors using cellos-acp package (official agent-client-protocol SDK) + fake_acp for testing.

### Files to Create
```
cellos/
└── connectors/
    ├── __init__.py
    ├── base.py                 # TaskConnector Protocol definition
    ├── cellos_acp.py           # CellosAcpConnector wrapping AcpClient
    └── fake_acp.py             # Canned response connector for testing
```

### Key Design Decisions
- `TaskConnector` is a typing.Protocol (duck typing, no inheritance)
- cellos-acp package provides `AcpClient` with official SDK — no hand-rolled JSON-RPC
- Agent registry in cellos-acp: opencode, hermes, claude, codex, openclaw, pi
- Model override via `OPENCODE_CONFIG_CONTENT` env var for opencode
- fake_acp supports fixture-based responses AND configurable defaults

### Acceptance Criteria
- [ ] CellosAcpConnector wraps AcpClient, passes agent name, cwd, env, timeout
- [ ] Agent resolved from cellos-acp registry (opencode default)
- [ ] FakeAcpConnector returns deterministic results from fixtures or defaults
- [ ] Both connectors implement TaskConnector Protocol correctly
- [ ] Timeout handling works (no hanging on unresponsive agents)
- [ ] Test file `tests/test_acp.py` covers connectors with mocks (~8 tests)
- [ ] fake_acp fixture-based testing enables full lifecycle without real agents
- [ ] `pytest -q` passes

---

## Phase 7: Prompt Builder + Structured Actions
**Goal**: Configurable prompt assembly and child task planning from agent output.

### Files to Create/Update
```
cellos/
├── prompt_builder.py           # build_task_prompt() assembling parts from profiles
└── task_actions.py             # parse_create_task_actions(), task_from_create_action()
```

### Key Design Decisions
- ALL prompts built from configurable parts — zero hardcoded strings
- Structured actions parsed from fenced code blocks, plain JSON, or nested format
- Child tasks created with parent_id reference; parent depends on children (not vice versa)
- Research tasks can be pre-approved (configurable) vs defaulting to NEEDS_APPROVAL

### Acceptance Criteria  
- [ ] Prompt builder assembles: role instructions + mode sections + task details + criteria + plan + comments + conversation + output format
- [ ] Structured action parsing handles all three formats (fenced/plain/nested)
- [ ] Child tasks created with correct parent_id; parent depends on children (not vice versa)
- [ ] Pydantic validation on parsed actions with clear error messages
- [ ] Test file `tests/test_prompt_builder.py` covers all prompt sections (~13 tests)
- [ ] Test file `tests/test_task_actions.py` covers parsing + child creation (~12 tests)
- [ ] `pytest -q` passes

---

## Phase 8: Worker Service + Subprocess Isolation  
**Goal**: Workers run as detached subprocesses with their own SQLite connections. Hung workers don't kill the scheduler.

### Files to Create
```
cellos/services/
├── worker_service.py           # Build connector → build prompt → run task → save result
└── worker_spawner.py           # Spawn detached subprocess via Popen(start_new_session=True)
```

Plus CLI command update:
- `worker <task_id> --mode planning|execution` — Execute single task (called by spawner)

### Key Design Decisions
- Workers are independent Python processes (`python -m cellos.cli worker`)
- Each has its own SQLite connection — no shared state with scheduler process  
- Logs written to `logs/worker-{id}.log` in project directory
- PYTHONPATH injected for package importability in spawned subprocess

### Acceptance Criteria
- [ ] WorkerService builds connector from agent config, runs prompt, saves result
- [ ] Planning mode: fetches comments for context; execution mode does not
- [ ] Task transitions to IN_PROGRESS before worker starts (prevents double-scheduling)
- [ ] Attempt lifecycle tracked: start → run via connector → save result → complete attempt
- [ ] WorkerSpawner creates detached subprocess with log file output
- [ ] `cellos.cli worker` command works when called directly or by spawner
- [ ] Test file `tests/test_worker.py` covers service logic (~8 tests)  
- [ ] Manual test: spawn worker with fake_acp, verify result saved and log created
- [ ] `pytest -q` passes

---

## Phase 9: Event-Driven Daemon (cellos run)
**Goal**: asyncio.Event-based scheduler that wakes only when work is available — no polling. Workers and human actions signal the daemon to re-evaluate scheduling.

### Files to Create/Update
```
cellos/services/
└── scheduler.py                # SchedulerService + DaemonService with event-driven loop
```

Plus CLI command:
- `run` — Start event-driven daemon (no interval param; sleeps until signaled)

### Key Design Decisions
- **No heartbeat polling** — uses `asyncio.Event()` to sleep until woken. Zero wasted CPU cycles, no SQLite contention from constant polling.
- **Signal sources**: Worker subprocess exits → scheduler wakes and re-evaluates. Human CLI actions (approve, update, add-task) write notification file → daemon watches for changes.
- Priority ordering: attention tasks → planning candidates → approved unblocked execution tasks
- Bounded concurrency: global `concurrent_tasks` cap + per-connector limits via `connector_concurrency` map (e.g., `cellos_acp: 1`, `fake_acp: 8`)
- Graceful shutdown on SIGINT/SIGTERM: wait for running workers, cleanup connections

### Acceptance Criteria
- [ ] Daemon sleeps on `asyncio.Event()` — no polling loop or idle counter
- [ ] Worker completion signals daemon to re-evaluate scheduling (via process status check)
- [ ] Human CLI actions write notification file; daemon watches and wakes on change
- [ ] pick_work() queries scheduler in priority order and spawns workers for selected tasks
- [ ] Concurrent task limit respected per cycle  
- [ ] Workers spawned as detached subprocesses (verified by log file creation)
- [ ] `cellos run` starts daemon, processes available work, stays idle until signaled
- [ ] SIGINT/SIGTERM triggers graceful shutdown: waits for running workers, cleans up connections
- [ ] Test file `tests/test_scheduler.py` covers scheduling logic + event-driven wake (~8 tests)
- [ ] Manual test: create draft task → cellos run picks it up for planning → fake_acp generates plan → status shows needs_approval
- [ ] `pytest -q` passes

---

## Phase 10: Integration Polish + Full Test Suite
**Goal**: Complete CLI surface area, comprehensive tests, smoke test document.

### Files to Create/Update
```
cellos/cli.py                  # Add: plan, execute commands (manual ACP triggers)
tests/test_integration.py       # End-to-end lifecycle tests
docs/smoke-test.md              # 15-step sequential validation flow
README.md                       # Full documentation with examples
```

### Acceptance Criteria
- [ ] `plan <task_id>` command: manual planning trigger via ACP (with fake_acp fallback)  
- [ ] `execute <task_id>` command: manual execution trigger via ACP (with fake_acp fallback)
- [ ] Full test suite passes: models, config, persistence, services, CLI, ACP, prompt_builder, task_actions, worker, scheduler (~107+ tests total)
- [ ] Smoke test document covers: init → create tasks → daemon picks work → planning generates plan with child task descriptions → human approves → execution creates children → children planned, approved, executed → parent completes → results visible
- [ ] README has full lifecycle example with commands and expected output
- [ ] Example configs are functional (fake_acp agents, complete prompt profiles)
- [ ] `pytest -q` passes all tests

---

## Phase Progress Tracking

Update this section as each phase completes:

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Models | ✅ Done | All enums + Pydantic models with backward-compat migration |
| 2. Persistence | ✅ Done | SQLite schema, repos, DB facade (json_extract indexes) |
| 3. Config | ✅ Done | Three-file config loading + example configs |
| 4. Services | ✅ Done | TaskService CRUD/approval/attention, Planning/Execution services |
| 5. CLI Foundation | ✅ Done | 8 commands: init, add-task, status, detail, approve, comment, events, update (17 tests) |
|| 6. ACP + Connectors | ✅ Complete | cellos-acp package integration, connectors/ (base protocol, cellos_acp, fake_acp) — migrated from acpx |
| 7. Prompt Builder + Actions | ✅ Done | prompt_builder.py, task_actions.py (+28 tests) |
| 8. Worker Isolation | ✅ Done (2026-05-21) | `worker_service.py` + `worker_spawner.py`, CLI worker cmd, 19 tests (agent resolution by role, attempt tracking, failed connector handling, e2e CLI) |
| 9. Daemon Scheduler | ✅ Done | `scheduler.py` (SchedulerService + DaemonService), CLI run cmd, notification file, 34 tests |
| 10. Integration Polish | ✅ Done | plan/execute CLI commands, 41 integration tests, smoke-test.md, README |
| 11. Tools Enhancement | ✅ Done | tool-calling migration, tools.json, toolprofiles.json, prompt_library.json, structured_result flow |
| — | | `json_util.py` in persistence |
| **Total** | | **316+ tests** across 13 test files |
