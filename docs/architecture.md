# CelloS Architecture

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Layer                            │
│  Click commands → Rich output (tables, panels, markdown)    │
│  Commands: init, add-task, status, detail, approve,         │
│            comment, events, update, run, plan, execute      │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌────────────────────────┐    ┌──────────────────────────────┐
│     Services Layer     │    │   Event-Driven Daemon        │
│                        │    │                              │
│  TaskService           │    │  asyncio.Event-based wake:   │
│  PlanningService       │    │    - Worker completes →      │
│  ExecutionService      │    │      signals scheduler       │
│  WorkerService         │    │    - Human action (approve,  │
│                        │    │      update) → signals        │
│  Responsibility:       │    │                              │
│  Business logic, state │    │  pick_work() →               │
│  machine enforcement   │    │    1. Attention tasks         │
└───────────┬────────────┘    │    2. Planning candidates     │
            │                 │    3. Approved unblocked      │
            ▼                 │                              │
                           spawn_workers() →                │
                             subprocess.Popen(              │
                               python -m cellos.cli        │
                               worker <id> --mode ...)      │
            ▼                                │
┌────────────────────────┐                   │
│     Persistence Layer  │◄──────────────────┘
│                        │   (workers connect to same SQLite)
│  CellosDatabase        │
│    → TaskRepository    │
│    → ResultRepo        │
│    → EventRepository   │
│    → CommentRepository │
│    → AttemptRepository │
│                        │
│  Pattern: function-based repos               │
│  taking aiosqlite.Connection as first param  │
└───────────┬────────────┘
            ▼
┌────────────────────────┐
│      SQLite Database   │
│    (aiosqlite)         │
│                        │
│  Tables: tasks, task_dependencies,           │
│          task_results, task_events,          │
│          task_comments, task_attempts        │
│                        │
│  Complex data stored as JSON columns:        │
│  conversation[], dependencies[],             │
│  attention{}, processing{}                   │
└────────────────────────┘

┌────────────────────────┐
│   ACP Connector Layer  │
│                        │
│  TaskConnector (Protocol):                    │
│    async run_task(task, workdir, mode,        │
│                  prompt_text) → TaskResult    │
│                        │
│  Implementations:                              │
│    - CellosAcpConnector: wraps cellos-acp      │
│      AcpClient (official agent-client-protocol │
│      SDK) with built-in agent registry         │
│    - FakeAcpConnector: canned responses        │
│      for testing (fixture-based or defaults)   │
└────────────────────────┘
```

## Module Boundaries

### CLI (`cellos/cli.py`)
- Click command group with `--db` and `--config` global options
- Each command wraps async logic in `asyncio.run(_inner())`
- Rich output: tables for status, panels for detail, markdown rendering
- Attention markers (⚠️) shown inline in task lists
- **No business logic** — delegates to services

### Services (`cellos/services/`)

| Module | Responsibility | Key Methods |
|--------|---------------|-------------|
| `task_service.py` | Task CRUD, attention tracking, approval gates | `create_task`, `update_task`, `approve_task`, `add_comment`, `add_conversation_message` |
| `planning_service.py` | Plan generation via ACP + result persistence with structured response parsing and thinking text stripping | `save_planning_result(db, task_id, plan_text)`, `_strip_thinking_text(plan_text)` |
| `execution_service.py` | Task execution result saving with structured response parsing, keyword fallback, and dependent wake-up | `save_execution_result(db, task_id, result_text)`, `_parse_execution_result(text)` |
| `scheduler.py` | Event-driven daemon (asyncio.Event wake) + work selection | `run_daemon()`, `pick_work()`, `spawn_workers(tasks)`, `_signal_work_available()` |
| `worker_service.py` | Worker lifecycle: build connector → run prompt → save result | `run_task_worker(task_id, mode)`, `_build_connector(agent_config)` |
| `worker_spawner.py` | Subprocess spawning with process isolation | `spawn(task_id, mode)` via `subprocess.Popen(start_new_session=True)` |

### Persistence (`cellos/persistence/`)

**Pattern**: Function-based repositories (not classes). Each module exports async functions taking `aiosqlite.Connection` as first parameter. This keeps things simple — no shared connection management in repos, the caller owns the connection lifecycle.

| Module | Responsibility |
|--------|---------------|
| `schema.py` | SQL DDL strings + `init_db()` + `ensure_initialized()` |
| `task_repository.py` | Task CRUD + scheduler queries (`list_attention_tasks`, `list_planning_candidates`, `list_approved_unblocked`) |
| `result_repository.py` | Result saving + side effects (wake blocked dependents, add dependency result comments) |
| `event_repository.py` | Event logging for audit trail |
| `comment_repository.py` | Comment storage and retrieval |
| `attempt_repository.py` | Attempt tracking per task execution try |
| `json_util.py` | JSON serialization/deserialization helpers for SQLite JSON columns, with datetime handling and Pydantic model round-tripping |

**Database facade**: `cellos/db.py` wraps all repository operations, handles commits, event recording, and side effects at transactional boundaries.

### ACP Integration (`cellos-acp` package)

Cellos uses the `cellos-acp` package, which wraps the official
`agent-client-protocol` Python SDK. The `CellosAcpConnector` creates an
`AcpClient` instance per task execution:

1. Resolve agent from cellos-acp registry (opencode, hermes, claude, codex, etc.)
2. Spawn agent subprocess with proper environment
3. Send prompt → stream events via official SDK
4. Collect text, thinking, and tool call results
5. Return structured `AcpRunResult` with combined output

Model override is supported via `OPENCODE_CONFIG_CONTENT` env var for opencode agent.

### Connectors (`cellos/connectors/`)

**Protocol-based interface** (duck typing without inheritance):

```python
class TaskConnector(Protocol):
    async def run_task(task: Task, workdir: str, mode: str, prompt_text: str) -> TaskResult: ...
```

  - **CellosAcpConnector**: Wraps cellos-acp `AcpClient` which uses the official `agent-client-protocol` SDK. Agent resolved from built-in registry (opencode, hermes, claude, codex, openclaw, pi). Model override via `model` field in agent catalog entry, passed through `OPENCODE_CONFIG_CONTENT` env var.

- **FakeAcpConnector**: Deterministic test connector. Fixture-based lookup: `{task_id}-{mode}.json` → `{mode}.json` → `default.json`. Falls back to configurable defaults (`default_success`, `default_summary`). Supports simulated delay for timing tests.

### Configuration (`cellos/config.py`)

Config files live in `~/.cellos/` by default. Example files shipped with the repo are copied on first init. The CLI accepts `--config-dir <path>` to point to a different config directory.

Three JSON files loaded into Pydantic models:

| File | Purpose |
|------|---------|
| `config.json` | Scheduler (concurrent_tasks), worker (backend, timeout), agents runtime (default_agent_id, catalog_path), approvals (preapprove_research_tasks), prompts (profiles_path) |
| `agentcatalog.json` | Map of agent_id → AgentCatalogEntry (connector type, model, options dict) |
| `promptprofiles.json` | Role instructions, mode-specific sections (planning/execution), output format requirements, final instructions |

Example files shipped at repo root: `cellos.config.json.example`, `agentcatalog.json.example`, `promptprofiles.json.example`. On first `init --overwrite`, these are copied to the config directory as `config.json` / `agentcatalog.json` / `promptprofiles.json`.

**Config sub-models**: `SchedulerConfig` (concurrent_tasks, heartbeat_interval_seconds), `WorkerConfig` (backend, timeout_seconds), `AgentRuntimeConfig` (default_agent_id, catalog_path), `ApprovalConfig` (preapprove_research_tasks), `PromptRuntimeConfig` (profiles_path). The `AgentCatalogEntry` model includes a `model` field for per-agent model override, passed via agent-specific env var.

**preapprove_research_tasks**: Boolean flag (default: false). When true, child tasks of type `research` created via structured actions auto-transition to APPROVED status instead of NEEDS_APPROVAL. All other task types still require human approval.

### Prompt Builder (`cellos/prompt_builder.py`)

Assembles prompts from configurable parts:
1. Task metadata (role, type, title, status)
2. Role instructions from profiles ("You are an engineer...")
3. Mode-specific instructions (planning vs execution)
4. Task details, success/failure criteria, plan text
5. Comments separated into research results and normal comments
6. Conversation history (for planning mode)
7. Output section format requirements from profiles
8. Final instructions

All externalized to `promptprofiles.json` — no hardcoded prompt strings.

### Structured Response Parsing (`cellos/structured_response.py`)

Parses agent output into typed Pydantic models using bracket-scanning JSON extraction that handles chatty LLM output with prose mixed in.

**Planning responses**: `parse_planning_response(text)` → `PlanningResponse` with `PlanSpec` (objective, steps, approach, verification, dependencies, risks) and `ChildTaskSpec` list (title, role, task_type, details, success/failure criteria, dependencies, blocks_parent). The `plan_to_text()` helper converts a `PlanningResponse` to readable markdown for storage as `task.plan`. The `child_tasks_from_response()` helper converts child task specs to task creation dicts with parent dependency tracking.

**Execution responses**: `parse_execution_response(text)` → `ExecutionResponse` with summary, success flag, actions_taken, files_changed, commands_run, criteria_met, and issues lists.

Both planning and execution services attempt structured response parsing first, falling back to keyword/regex-based parsing for non-JSON output.

### Structured Actions (`cellos/task_actions.py`)

Parses agent output for child task creation:

```json
{
  "actions": [
    {
      "type": "create_task",
      "title": "Implement authentication module",
      "role": "engineer",
      "task_type": "implementation",
      "prompt": "...",
      "dependencies": ["parent-task-id"],
      "blocks_parent": true
    }
  ]
}
```

Supports: fenced code blocks, plain JSON, nested action format. Validates with Pydantic. Creates child tasks with dependency tracking and parent blocking logic.

## Runtime Flow: Event-Driven Daemon (`cellos run`)

The daemon uses `asyncio.Event` instead of polling/heartbeat. It sleeps until signaled that work is available, then wakes up and processes it. This eliminates wasted CPU cycles and SQLite contention from constant polling.

**Signal sources (anything that makes work available):**
1. **Worker completion**: When a worker subprocess exits, the scheduler detects this via process status check → signals itself to re-evaluate scheduling (completed workers may have unblocked dependents or created child tasks)
2. **Human CLI actions**: `approve`, `update`, `add-task` commands write to a notification file in `notify/` (project directory) that the daemon watches — any change wakes it up

```
1. Load config + connect to SQLite
2. Run initial work selection pass (pick_work)
3. Enter event loop:
   a. await asyncio.Event() — blocks until signaled
   b. On wake: pick_work in priority order:
      - Tasks requiring attention (attention.required = true)
      - Planning candidates (draft tasks ready for planning)
      - Approved unblocked tasks (dependencies satisfied)
   c. For each task to schedule: spawn worker subprocess via WorkerSpawner
   d. Register callback: when spawned workers exit → set event again
4. Graceful shutdown on SIGINT/SIGTERM: wait for running workers, cleanup connections
```

**Why not heartbeat polling?** Polling every N seconds wastes CPU and creates SQLite write contention (each poll opens a connection). Event-driven only wakes when something actually changed — worker finished or human took action.

## Runtime Flow: Worker Subprocess (`cellos.cli worker`)

```
1. Load config + connect to SQLite (separate connection from scheduler)
2. Fetch task by ID
3. Transition task status → IN_PROGRESS (signals "a worker has this")
4. Build connector from agent config in catalog
5. Build prompt via PromptBuilder with mode-specific sections
6. Run connector → get TaskResult
7. Save result:
   - Planning mode: save_planning_result() → sets NEEDS_APPROVAL
   - Execution mode: save_execution_result() → parse actions, create children, set DONE/FAILED
8. Record attempt + event in database
9. Write log to logs/worker-{id}.log (project directory)
10. Exit subprocess
```

The IN_PROGRESS transition at step 3 is meaningful — it prevents the scheduler from picking up the same task again if a worker crashes mid-execution, and provides visibility into which tasks are currently being worked on. If the worker fails before completing, the next scheduling pass sees IN_PROGRESS and can retry (after timeout) or mark FAILED.

## Error Handling Strategy

| Scenario | Behavior |
|----------|----------|
| Worker subprocess hangs | Timeout kills it; scheduler wakes on event and reschedules remaining work |
| ACP agent crashes | Caught by worker_service → attempt marked FAILED → event logged |
| Database locked | SQLite handles concurrent reads; writes are serialized via aiosqlite |
| Config file missing/invalid | Pydantic validation error with clear message at startup |
| Task in wrong state for operation | Custom exception (e.g., `InvalidTaskApprovalError`) → CLI prints error |
| Agent binary not found | CellosAcpConnector returns failure result; use fake_acp for testing |

## Testing Strategy

### Unit Tests (`tests/test_*.py`)
- **No mocking of DB layer** — use real temp SQLite databases via pytest fixtures
- Test all models: enums, Pydantic validation, backward-compat migrations
- Test services: full lifecycle flows with in-memory DBs
- Test CLI integration: Click's `CliRunner` for end-to-end command testing

### Fake Agent Testing
- **FakeAcpConnector** enables complete lifecycle testing without real ACP agents
- Fixture-based responses: task-specific, mode-specific, or default canned results
- Supports structured action JSON in fixtures to test child task creation flow

### Smoke Test (`docs/smoke-test.md`)
Sequential validation covering: init → create tasks → daemon scheduler picks work → planning generates plan + children → human approves → execution completes → results visible. ~15 steps validating the full system integration.
