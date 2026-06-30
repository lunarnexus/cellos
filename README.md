# CelloS

Human-governed AI orchestration system that decomposes project work into small, reviewable tasks routed to specialized worker agents. The human stays in control at every meaningful decision point.

## Installation

**Prerequisites:** Python 3.12+ and `pipx`.

Install CelloS as a normal CLI command:

```bash
cd ~/workspace/cellos
pipx install --python python3.12 --editable .
cellos init
```

### Notes

- `--python python3.12` matters because CelloS requires Python 3.12+.
- `--editable` keeps the installed `cellos` command pointing at this working tree, so source edits are picked up without reinstalling.
- Reinstall only when packaging metadata or dependencies change.

Verify the install:

```bash
cellos --help
```

For local development with test dependencies:

```bash
cd ~/workspace/cellos
pipx install --python python3.12 --editable ".[dev]"
```

## Quick Start

```bash
cellos init
cellos add-task "Build user authentication" -d "Implement JWT-based auth with bcrypt" -r engineer
cellos status
cellos plan <task_id>
cellos detail <task_id>
cellos approve <task_id>
cellos execute <task_id>
cellos run
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `init [--overwrite]` | Create config files and database |
| `add-task <title> [-d details] [-r role] [-t type] [-s success] [-f failure] [--depends ids]` | Create task |
| `status [-s status_filter]` | List tasks with attention markers |
| `detail <task_id>` | Full task info |
| `approve <task_id>` | Approve NEEDS_APPROVAL task |
| `comment <task_id> -m message` | Add human comment + trigger attention |
| `events <task_id> [--limit N]` | Show audit trail |
| `update <task_id> [...]` | Update task fields |
| `plan <task_id>` | Generate a plan via agent |
| `execute <task_id>` | Execute approved task via agent |
| `worker <task_id> --mode planning\|execution` | Run single worker |
| `run` | Start daemon scheduler |
| `pmcon list` | List available PM tool providers |
| `pmcon setup <provider>` | Bootstrap a provider |
| `pmcon sync <provider> [--push] [--pull]` | Sync with an external provider |
| `pmcon status <provider>` | Show provider configuration/status |

## PM Integrations

CelloS keeps a generic provider interface under `cellos/integrations/`.

Current state:
- generic integration scaffolding is present
- **Vikunja** is implemented as the first real PM connector
- the next planned providers remain **WeKan**, **Plane**, and **OpenProject**

See:
- `docs/connectors.md`
- `docs/provider-roadmap.md`
- `docs/archive/provider-implementation-plan.md` for the historical provider implementation plan
- `docs/vikunja-smoke-test.md` for the Vikunja connector smoke test

## Configuration

Three JSON files in `~/.cellos/`:

**config.json**
```json
{
  "scheduler": { "concurrent_tasks": 4, "heartbeat_interval_seconds": 5.0 },
  "worker": { "backend": "acp", "timeout_seconds": 300 },
  "agents": { "default_agent_id": "engineer" },
  "integrations": {
    "enabled_providers": [],
    "providers": {}
  }
}
```

**agentcatalog.json**
```json
{
  "engineer": { "connector": "fake_acp", "options": { "default_success": true } }
}
```

**promptprofiles.json**
- role instructions and mode-specific prompt sections

## Architecture

- deterministic scheduling with event-driven daemon
- protocol-based ACP connectors for agent communication
- repository-pattern persistence with SQLite
- generic PM integration/provider contract under `cellos/integrations/`

## Testing

```bash
python -m pytest tests/ -v
python -m pytest tests/ -q
```

See `docs/smoke-test.md` for the generic smoke test.
