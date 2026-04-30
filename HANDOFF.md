# CelloS — Session Handoff
This document hands essential context from one coding-agent session to the next. Preserve only the information needed to resume work: current decisions, project status, and the most recent progress checkpoint. Broader product vision belongs in `docs/`.


## Current State

- **Repository**: https://github.com/lunarnexus/cellos
- **Working directory**: `/Users/james/Scripts/CelloS/cellos`
- **Python**: 3.11+
- **Phase**: MVP foundation / internal engine

## Most Recent Progress

- Removed `aiohttp`; `httpx` is the async HTTP client.
- Changed MVP PM choice from Linear to Trello.
- Removed Scrum from the MVP handoff; MVP workflow is Trello-style Kanban.
- Added parallel ready-task spawning to MVP scope.
- Named agent roles:
  - Conductor → Plan / Coordinate
  - Composer → Design
  - Cello → Build
  - Critic → Verify
- Created `cellos/models.py` with core Pydantic domain models.
- Created `cellos/db.py` with async SQLite persistence and a ready-task query.
- Created `cellos/acp.py` as a generic ACP JSON-RPC client.
- Created `cellos/connectors/opencode.py` for OpenCode-specific ACP behavior.
- Created `cellos/orchestrator.py` for parallel ready-task execution.
- Created `cellos/cli.py` with the first usable local CLI loop.
- Verified a real OpenCode ACP task end-to-end: `task-fba0ea22: done - CELLOS_ACP_OK`.
- `cellos status` now shows a `Response` column populated from saved task results.

## Tech Stack

```
aiosqlite>=0.20
httpx>=0.27
rich>=13.0
pydantic>=2.0
pydantic-settings>=2.0
click>=8.0
```

- **Async**: yes (asyncio throughout)
- **Config/Schema**: JSON + pydantic
- **State**: SQLite (aiosqlite), CelloS is source of truth

## PM Tool Decision: Trello (final choice)

### Why Trello
- Simple Kanban model
- Very familiar/popular workflow
- Low setup overhead
- Good fit for personal MVP planning
- Cards/lists are enough for the first orchestration loop

### Tradeoffs
- No native task dependencies
- No built-in approval workflow
- Checklists are not independent task cards
- Advanced hierarchy will live inside CelloS, not Trello

### Alternatives Considered
| Tool | Verdict |
|------|---------|
| Plane | Best self-hosted, but maintenance overhead |
| Jira | Too complex, enterprise-focused |
| ClickUp | Overwhelming, inconsistent API |
| Linear | Strong structured PM tool, but more than the MVP needs |

## MVP Workflow

### Trello Kanban Lifecycle
```
Backlog ──► To Do ──► In Progress ──► Done
    │          │           │              │
 You add   Priority    CelloS          Results
 ideas     work        works
```

### Scheduler Heartbeat

`cellos run` is one scheduler heartbeat, not a forever loop. Each invocation finds ready unblocked tasks, runs one bounded batch, saves results, and exits. This keeps production supervision simple: cron, launchd, systemd, or a future PM webhook can call `cellos run` repeatedly.

- Default concurrency: `cellos run --concurrent-tasks 4`
- Timeout meaning: worker execution timeout for that task attempt, defaulting to `300` seconds. Per-task `--timeout` can still override it for longer jobs.
- Passive status: `cellos status` reads known state from SQLite only.
- Active status hook: `cellos status --check-tasks` is the planned entry point for probing in-progress workers. With the current one-process-per-task backend, active checks report that probing is not available yet.

## ACP Protocol

CelloS communicates with worker agents via **Agent Client Protocol (ACP)** — JSON-RPC 2.0 over stdio.

**Spec:** https://agentclientprotocol.com

**Key reference:** `docs/acp-guide.md`

Implementation note: `cellos/acp.py` stays generic. Agent-specific behavior belongs in connector modules such as `cellos/connectors/opencode.py`.

Response extraction uses ACP `agent_message_chunk` updates and ignores `agent_thought_chunk` reasoning updates.

### How It Works
```
CelloS                          Worker Agent
   │                                  │
   │──── initialize ─────────────────►│  (once at spawn)
   │◄──── capabilities ───────────────│
   │                                  │
   │──── session/new ─────────────────►│
   │◄──── sessionId ──────────────────│
   │                                  │
   │──── session/prompt ─────────────►│  (send task)
   │◄──── session/update ────────────│  (streaming response)
   │◄──── session/prompt result ────│
   │                                  │
```

### Profile Loading (at spawn time, not via protocol)
- Hermes: `hermes -p <profile> acp`
- OpenClaw: `openclaw acp --agent <agentId>`
- OpenCode: `opencode acp`

One process per agent. CelloS spawns multiple workers in parallel.

## Agent Architecture

**Paperclip pattern:**
- CelloS is control plane only
- Workers manage their own memory/prompts
- CelloS maps roles → agent profiles → spawn commands
- Adapters handle agent-type differences

```
CelloS (Orchestrator)
├── spawn worker 1: hermes -p composer acp
├── spawn worker 2: OpenCode via `opencode acp`
│
├── send task to worker 1
├── send task to worker 2
│
└── collect results
```

## MVP Scope

### What's In
1. aiosqlite for data storage
2. Trello as PM tool
3. OpenCode as default agent
4. ACP client to spawn agents
5. Simple conductor (analyze task → plan)
6. Orchestrator loop with parallel task spawning

### What's Out (for now)
- PM heartbeat monitoring
- Cost tracking
- Escalation/loop detection
- Approval gates (auto-approve MVP)

### Build Order
1. `models.py` — Core Pydantic domain models (**done**)
2. `db.py` — SQLite schema + CRUD (**done**)
3. `agents.py` — Shared backend protocol and prompt builder (**done**)
4. `acp.py` — Generic ACP client (**done**)
5. `connectors/opencode.py` — OpenCode ACP connector (**done**)
6. `orchestrator.py` — Main loop with parallel ready-task spawning (**done**)
7. `cli.py` — Entry points and progress display (**done**)
8. `pm/trello.py` — Trello adapter after internal loop works

## Agent Hierarchy

- Conductor → Plan / Coordinate
- Composer → Design
- Cello → Build
- Critic → Verify

All executed via ACP (spawn worker subprocess).

## Worker Spawn Commands

**OpenCode (default):**
```bash
opencode acp
```

**Hermes:**
```bash
hermes -p <profile-name> acp
```

**OpenClaw:**
```bash
openclaw acp --agent <agentId>
```

## Next (updated)

**Immediate: Trello Integration & UI**

1. Build `pm/trello.py` adapter for Trello Kanban sync.
2. Improve CLI UI/UX: better task display, interactive editing, and status formatting.
3. Create richer local test tasks that exercise real file edits and verification.
4. Add task decomposition flow: Conductor creates child tasks, workers execute ready tasks.

**Then:**
- Additional PM adapters (Notion, Jira, etc.)
- Cost tracking
- Escalation

## Real Integration Test Recipe

Run from `/Users/james/Scripts/CelloS/cellos` without Codex sandboxing:

```bash
cellos reset-db --yes
cellos add-task "Create tmp test note" --description "Create tmp/cellos-real-test.txt containing exactly CELLOS_FILE_EDIT_OK. Keep the change minimal." --type build --role cello
cellos add-task "Verify tmp test note" --description "Verify tmp/cellos-real-test.txt exists and contains exactly CELLOS_FILE_EDIT_OK. Report only the result." --type test --role critic --depends-on <build-task-id>
cellos run
cellos run
cellos status
```

Expected result: the first run creates `tmp/cellos-real-test.txt`, the second run verifies it, and both tasks end as `done`.

## Notes

- Docs before code
- One file at a time
- Workers own their memory (no vector DB)
- PM tool is just interface layer — CelloS manages complexity internally
- Real CelloS/OpenCode integration tests should run from `/Users/james/Scripts/CelloS/cellos` without Codex sandboxing. Sandboxed runs caused OpenCode local state/log DB failures such as `PRAGMA wal_checkpoint(PASSIVE)`, while the same tasks succeeded outside the sandbox.
- Verification checkpoint: `pytest tests/test_acp.py tests/test_agents.py tests/test_orchestrator.py tests/test_cli.py` passes.
- **Multi-agent development**: This project is actively worked on by multiple AI agents (Codex and Hermes). To avoid conflicts, split work by file/module ownership. Use `HANDOFF.md` to sync state between sessions/agents. Recommended split: one agent owns `pm/` + Trello integration + testing, the other owns `cli.py` + UI improvements + task decomposition.

## Relevant Docs

- `docs/acp-guide.md` — ACP protocol implementation guide
- `docs/tech.md` — Architecture overview
- `docs/strategy.md` — Product vision
