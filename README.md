# CelloS

This is pre-alpha software.  Use appropriate guardrails when working with AI workflows.  

Human-governed AI orchestration system that decomposes project work into small, reviewable tasks routed to specialized worker agents. The human stays in control at every meaningful decision point.

Compliance and auditing of AI workflows aligned with SOC 2, NIST AI RMF, ISO 27001 and MITRE ATLAS among others.  

## Installation

```bash
cd cellos
pip install -e ".[dev]"
cellos init
```

## Quick Start — Full Lifecycle

```bash
# Initialize project with config files and database
cellos init

# Create a task
cellos add-task "Build user authentication" \
  -d "Implement JWT-based auth with bcrypt" \
  -r engineer

# View tasks
cellos status

# Generate plan (via agent)
cellos plan <task_id>

# Review and approve
cellos detail <task_id>
cellos approve <task_id>

# Execute task
cellos execute <task_id>

# Start daemon scheduler
cellos run
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `init [--overwrite]` | Create config files and database |
| `add-task <title> [-d details] [-r role] [-t type] [-s success] [-f failure] [--depends ids]` | Create task |
| `status [-s status_filter]` | List tasks with ⚠️ attention markers |
| `detail <task_id>` | Full task info (plan, conversation, comments) |
| `approve <task_id>` | Approve NEEDS_APPROVAL task (human gate) |
| `comment <task_id> -m message` | Add human comment + trigger attention |
| `events <task_id> [--limit N]` | Show audit trail |
| `update <task_id> [--title] [--status] [--add-dep] [--remove-dep]` | Update any field |
| `plan <task_id>` | Generate plan via agent (manual trigger) |
| `execute <task_id>` | Execute approved task via agent (manual trigger) |
| `worker <task_id> --mode planning\|execution` | Run single worker (called by spawner) |
| `run` | Start event-driven daemon scheduler |

## Configuration

Three JSON files in `~/.cellos/`:

**config.json** — Scheduler, worker, and agent settings:
```json
{
  "scheduler": { "concurrent_tasks": 4, "heartbeat_interval_seconds": 5.0 },
  "worker": { "backend": "acp", "timeout_seconds": 300 },
  "agents": { "default_agent_id": "engineer" }
}
```

**agentcatalog.json** — Agent definitions:
```json
{
  "engineer": { "connector": "fake_acp", "options": { "default_success": true } }
}
```

**promptprofiles.json** — Role instructions and mode-specific prompt sections.

## Task Lifecycle

```
draft ──▶ needs_approval ──▶ approved ──▶ done
  │              ▲               │          │
  │         [plan]             execute    failed
  │              │              (agent)     │
  └────── [approve] ←──────────┘            │
           (human gate)                      │
                                            cancelled
```

Attention signals trigger on: human changes, comments, planning complete, dependency done.

## Architecture

- **Deterministic scheduling** with event-driven daemon (no polling)
- **Protocol-based ACP connectors** for agent communication
- **Repository pattern** persistence with SQLite
- **Rich CLI output** with attention tracking
- **Subprocess worker isolation** (hung workers don't kill scheduler)

See `docs/` for detailed architecture, data model, and build plans.

## Testing

```bash
python -m pytest tests/ -v      # Full test suite
python -m pytest tests/ -q      # Quiet mode
```

See `docs/smoke-test.md` for the 15-step sequential validation flow.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Config not found | Run `cellos init` |
| Cannot approve draft task | Task must be in `needs_approval` status |
| Worker error with acpx | Falls back to `fake_acp` automatically |
| Daemon exits quickly | Exits after 60 idle cycles (~5 min); ensure tasks exist |
