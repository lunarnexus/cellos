# CelloS Project Charter

## What This Is

Human-governed AI orchestration system that decomposes project work into small, reviewable tasks routed to specialized worker agents. The human stays in control at every meaningful decision point.

## Non-Negotiable Design Principles

1. **Human Approval First** — Meaningful actions require approval gates before execution. Plans are reviewed by humans, not blindly executed.

2. **Small Focused Context** — Workers get only the context they need. Failed work starts fresh with a focused prompt, not an extended session. This is a *core design assumption*, not an optimization.

3. **Decompose By Default** — The planning system biases toward breaking tasks into smaller reviewable units rather than optimistic one-shot execution. Child task creation via structured JSON actions is vital.

4. **Deterministic Orchestration** — Scheduler, state machine, dependency/approval checks are deterministic code; AI only reasons inside approved task boundaries. LLMs do NOT control scheduling or routing logic.

5. **SQLite Is Authoritative** — Internal SQLite database is the single source of truth for all project state. PM tools (for example WeKan, Plane, and OpenProject) are UI sync surfaces, not owners of orchestration logic.

6. **Best Effort & Recoverable** — One failure shouldn't stop unrelated work. Workers run as isolated subprocesses. Local state supports recovery on the next scheduling pass.

7. **Test Everything** — Every public function has a test. CLI commands have integration tests. The system must be testable end-to-end and built with Test Driven Development.

## Task Flow Architecture

```
User creates top-level task (title, details, pass/fail criteria)
  → Daemon scheduler picks it up as planning candidate
    → Worker spawns subprocess, calls Architect agent via ACP connector
      → Agent returns plan + structured child tasks in JSON blocks
        → Plan saved to task, status → NEEDS_APPROVAL
          → Human reviews plan (cellos detail), approves or comments
            On Comment: spawn another plan subprocess to review the plan based on comments.  status -> NEEDS_APPROVAL
            → On approval: scheduler picks approved tasks for execution
              → Worker spawns subprocess, calls Engineer agent via ACP connector
                → Agent executes work, may create more child tasks (if in approved plan)
                  → Results saved, status → DONE/FAILED
                    → Child task completion unblocks parent dependencies
```

## Target Users & Use Cases

- **Primary**: Developer using AI agents to decompose and execute project work
- **Workflow**: Create high-level task → architect plans decomposition → human approves plan → specialized sub-agents execute focused chunks → results aggregated
- **Interaction model**: CLI for testing and debugging with daemon scheduler running in background. Human intervenes via `cellos approve`, `cellos comment`, `cellos update`.
  Primary UI is through Project Management tools (for example WeKan, Plane, OpenProject)

## Scope: What's In and Out

### In (MVP)
- Local SQLite state management
- Event-driven daemon scheduler (`cellos run`) with asyncio.Event wake (no polling)
- Full task lifecycle: draft → planning → approval → execution → done/failed
- Structured action parsing for child task creation from agent output
- Subprocess worker isolation (hung workers don't kill scheduler)
- Protocol-based ACP connectors (opencode + fake_acp for testing)
- Rich CLI output (tables, panels, attention markers ⚠️)
- Attention system with reason codes and auto-triggering
- Dependency tracking between tasks
- Conversation logging (human/agent/system messages per task)
- Prompt profiles externalized to JSON config

### Out (Future)
- PM tool sync adapters (open-source PM connectors)
- Custom web UI
- Cost accounting / token usage tracking
- Long-lived worker pools (subprocesses spawn-per-task for now)
- Multi-project coordination
- Auto-approval policies (all require human gate in MVP)

## Agent Registry

The agent registry (`agentcatalog.json`) maps named agents to connector implementations and configuration options. It lives in the project directory alongside `config.json` and `promptprofiles.json`.

### Connector Implementations (code)

These are the actual execution backends — protocol-based connectors implementing the `TaskConnector` Protocol:

| Connector | Description |
|-----------|-------------|
| `fake_acp` | Deterministic canned responses for testing. Fixture-based or configurable defaults. No subprocess spawned — returns instantly. |
| `opencode` | Real ACP agent via OpenCode subprocess. Full JSON-RPC 2.0 over stdin/stdout. Planning, execution, and child task creation capabilities. |

### Registry Entries (configuration)

Each entry in `agentcatalog.json` is a named agent referencing one of the connector types above:

```json
{
  "engineer": { "connector": "opencode", "model": "qwen-2.5-7b-instruct" },
  "test-agent": { "connector": "fake_acp", "options": { "default_success": true } }
}
```

### Agent Selection Flow

1. Task created with `agent_id` field set → use that agent from the catalog
2. No agent specified on task → fall back to `config.agents.default_agent_id`
3. Agent ID not found in registry → fail worker attempt cleanly with error message

Agents can be extended by adding entries to the registry — no code changes required for new connector configurations. The five role-based agents (coordinator, researcher, architect, engineer, tester) are examples shipped in `agentcatalog.example.json`.

## Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.12+ | Ecosystem, async support |
| CLI Framework | Click + Rich | Command structure + formatted output |
| Async Runtime | asyncio + aiosqlite | Non-blocking I/O throughout |
| Data Validation | Pydantic v2 | Model validation, serialization, backward-compat migration |
| Database | SQLite (aiosqlite) | Zero-config local persistence, JSON columns for nested data |
| Agent Protocol | ACP (JSON-RPC 2.0 over subprocess stdin/stdout) | Standardized agent communication |
| Testing | pytest + pytest-asyncio | Real temp DBs, no mocking of DB layer |

## Success Criteria

1. All unit tests pass (`pytest -q`)
2. Full smoke test passes: init → create task → daemon picks up work → plan generated → human approves → execution completes → child tasks created and executed → results visible
3. Worker subprocess isolation verified (hung worker doesn't crash scheduler)
4. fake_acp connector enables full lifecycle testing without real agents
5. CLI is usable for all operations without reading documentation
