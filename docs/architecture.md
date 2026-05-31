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
│                  prompt_text, config) →        │
│                  ConnectorResult              │
│                        │
│  ConnectorResult:                                │
│    task_result: TaskResult                       │
│    structured_result: dict (from tool call)      │
│    tool_calls: list[ToolCallInfo]                │
│    diagnostics: dict                             │
│                        │
│  Implementations:                              │
│    - CellosAcpConnector: wraps cellos-acp      │
│      AcpClient with tool-calling. Resolves      │
│      tools from config.tool_profiles by         │
│      role+mode, passes output_tools to          │
│      AcpClient, extracts structured_result      │
│      and tool_calls from AcpRunResult           │
│    - FakeAcpConnector: canned responses        │
│      for testing. Fixture JSON supports         │
│      structured_result and tool_calls fields    │
└────────────────────────┘
```

## Module Boundaries

### CLI (`cellos/cli.py`)
- Click command group with `--db` and `--config-dir` global options
- Each command wraps async logic in `asyncio.run(_inner())`
- Rich output: tables for status, panels for detail, markdown rendering
- Attention markers (⚠️) shown inline in task lists
- **No business logic** — delegates to services

### Services (`cellos/services/`)

| Module | Responsibility | Key Methods |
|--------|---------------|-------------|
| `task_service.py` | Task CRUD, attention tracking, approval gates | `create_task`, `update_task`, `approve_task`, `add_comment`, `add_conversation_message` |
| `planning_service.py` | Save planning result from cellos_submit_prompt tool call | `save_planning_result(db, task_id, structured_result, success)`, `structured_result_to_plan_text(data)` |
| `execution_service.py` | Save execution result from cellos_submit_reply tool call | `save_execution_result(db, task_id, structured_result, wait_for_children)` |
| `scheduler.py` | Event-driven daemon (asyncio.Event wake) + work selection | `run_daemon()`, `pick_work()`, `spawn_workers(tasks)`, `_signal_work_available()` |
| `worker_service.py` | Worker lifecycle: resolve tools → build connector → run prompt → save structured result → handle cellos_create_task | `run_task_worker(task_id, mode, config)`, `_build_connector(agent_config)`, `_build_tool_defs_for_prompt(config, role, mode)` |
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
2. Resolve tools for role+mode from config → build `output_tools` list
3. Spawn agent subprocess with MCP server (from tool schemas)
4. Send prompt → stream events via official SDK
5. Agent calls tools (cellos_submit_prompt, cellos_submit_reply, etc.)
6. Extract `structured_result` from required tool, `tool_calls` from non-required
7. Return `ConnectorResult` with structured data

Model override is supported via `OPENCODE_CONFIG_CONTENT` env var for opencode agent.

### Connectors (`cellos/connectors/`)

**Protocol-based interface** (duck typing without inheritance):

```python
@dataclass
class ToolCallInfo:
    title: str  # e.g. "cellos_create_task"
    arguments: dict[str, Any]

@dataclass
class ConnectorResult:
    task_result: TaskResult
    structured_result: dict | None
    tool_calls: list[ToolCallInfo] | None
    diagnostics: dict | None

class TaskConnector(Protocol):
    async def run_task(task, workdir, mode, prompt_text, config) -> ConnectorResult: ...
```

  - **CellosAcpConnector**: Wraps cellos-acp `AcpClient`. Resolves tools for role+mode from `config.tool_profiles` and `config.tools`. Builds `output_tools` list with schemas. Passes to `AcpClient.run(output_tools=..., required_output_tool=...)`. Extracts `structured_result` from the required tool call and `tool_calls` for non-required calls (e.g., `cellos_create_task`). Model override via `model` field in agent catalog entry, passed through `OPENCODE_CONFIG_CONTENT` env var.

- **FakeAcpConnector**: Deterministic test connector. Fixture-based lookup: `{task_id}-{mode}.json` → `{mode}.json` → `default.json`. Falls back to configurable defaults. Fixture JSON supports `structured_result` dict and `tool_calls` list for testing tool-calling flows.

### Configuration (`cellos/config.py`)

Config files live in `~/.cellos/` by default. Example files shipped with the repo are copied on first init. The CLI accepts `--config-dir <path>` to point to a different config directory.

Six JSON files loaded into Pydantic models:

| File | Purpose |
|------|---------|
| `config.json` | Scheduler, worker, agents, approvals, prompts paths |
| `agentcatalog.json` | Map of agent_id → AgentCatalogEntry (connector type, model, options dict) |
| `promptprofiles.json` | Legacy role instructions and mode-specific prompt sections |
| `tools.json` | Tool registry — name, description, JSON schema for each tool |
| `toolprofiles.json` | Role+mode → tool mapping with explicit `required` field |
| `prompt_library.json` | Composable prompt fragments (roles, modes, tools_header, output_instruction) |

Example files shipped at repo root: `cellos.config.json.example`, `agentcatalog.json.example`, `promptprofiles.json.example`, `tools.json.example`, `toolprofiles.json.example`, `prompt_library.json.example`. On first `init --overwrite`, these are copied to the config directory.

**Config sub-models**: `SchedulerConfig`, `WorkerConfig`, `AgentRuntimeConfig`, `ApprovalConfig`, `PromptRuntimeConfig` (profiles_path, tools_path, tool_profiles_path, library_path). `ToolDefConfig` (description, schema), `ToolProfileEntry` (tools list, required tool name), `PromptLibraryConfig` (roles, modes, tools_header, output_instruction). The `AgentCatalogEntry` model includes a `model` field for per-agent model override.

**Tool resolution**: `get_tools_for_role_mode(profiles, role, mode)` returns (tool_names, required_tool). `validate_tool_profiles()` fails fast on startup if any tool reference is not found in `tools.json`.

**connector_concurrency**: Map of connector type → max concurrent workers (e.g., `{"cellos_acp": 1, "fake_acp": 8}`). Each connector type has its own pool. Unconfigured connectors default to 1. The global `concurrent_tasks` cap still applies as the total ceiling across all connectors.

**preapprove_research_tasks**: Boolean flag (default: false). When true, child tasks of type `research` created via tool calls auto-transition to APPROVED status instead of NEEDS_APPROVAL.

### Prompt Builder (`cellos/prompt_builder.py`)

Assembles prompts from `prompt_library.json` fragments + auto-injected tool list:
1. Role instruction — from `library.roles[role]`
2. Mode instruction — from `library.modes[mode]`
3. Available tools — auto-generated from `tool_defs` dict (field names only, not types — MCP provides full schemas)
4. Task metadata — title, role, type, status
5. Details, success/failure criteria
6. Comments (planning mode only)
7. Plan text (execution mode only)
8. Output instruction — from `library.output_instruction`

Tool list format: `• cellos_submit_reply — submit results (fields: summary, success, actions_taken, ...)`

### Tool-Calling Flow

LLM responses use structured tool calls instead of JSON text output. The flow:

1. **cellos** resolves tools for role+mode from `config.tool_profiles` and `config.tools`
2. **CellosAcpConnector** builds `output_tools` list with schemas → passes to `AcpClient.run(output_tools=..., required_output_tool=...)`
3. **cellos-acp** spawns ephemeral MCP server from schemas → agent discovers tools via MCP handshake
4. **Agent** calls tools (e.g., `cellos_submit_prompt`, `cellos_submit_reply`, `cellos_create_task`)
5. **CellosAcpConnector** extracts:
   - `structured_result` from the required tool call (e.g., plan data, execution result)
   - `tool_calls` for non-required calls (e.g., `cellos_create_task` for child tasks)
6. **Services** validate structured data and persist results

**Tools defined in `tools.json`:**
- `cellos_submit_prompt` — planning result (objective, steps, approach, verification, risks)
- `cellos_submit_reply` — execution result (summary, success, actions_taken, files_changed, issues)
- `cellos_create_task` — child task creation (title, role, details, success_criteria, failure_criteria)
- `cellos_report_blocker` — blocker report (reason, needed_from_human)

### Child Task Creation

Child tasks are created via `cellos_create_task` tool calls captured from `ConnectorResult.tool_calls`:

```python
for tc in conn_result.tool_calls:
    if tc.title == "cellos_create_task":
        child = await tservice.create_task(
            title=tc.arguments["title"],
            details=tc.arguments.get("details", ""),
            role=tc.arguments.get("role", "engineer"),
            ...
        )
```

Parent depends on children (not vice versa). Fire-and-forget with dependency tracking — worker creates children and exits, parent stays `APPROVED` until children complete via the dependency system.

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

**Why not heartbeat polling?** Polling every N seconds wastes CPU and creates SQLite write contention (each poll opens a connection). The primary mechanism is event-driven (asyncio.Event) — the daemon sleeps until signaled by worker exits or human CLI actions. A lightweight 0.5s file watcher provides cross-process notification as a fallback.

## Runtime Flow: Worker Subprocess (`cellos.cli worker`)

```
1. Load config + connect to SQLite (separate connection from scheduler)
2. Fetch task by ID
3. Transition task status → IN_PROGRESS (signals "a worker has this")
4. Resolve agent → build connector
5. Build prompt from prompt_library.json + inject tool list
6. Resolve tools for role+mode from config.tool_profiles
7. Run connector with config → get ConnectorResult:
    - structured_result from required tool call
    - tool_calls for non-required calls (e.g. cellos_create_task)
8. Save result:
    - Planning: save_planning_result(structured_result) → NEEDS_APPROVAL
    - Execution: handle cellos_create_task calls → create children
                   save_execution_result(structured_result) → DONE/FAILED
9. Record attempt + event in database
10. Write log to logs/worker-{id}.log (project directory)
11. Exit subprocess
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
- Fixture JSON supports `structured_result` dict and `tool_calls` list for testing tool-calling flows
- Auto-generates mode-appropriate structured result from defaults when no fixture matches

### Smoke Test (`docs/smoke-test.md`)
Sequential validation covering: init → create tasks → daemon scheduler picks work → planning generates plan + children → human approves → execution completes → results visible. ~15 steps validating the full system integration.
