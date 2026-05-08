# ACP Agent Execution

CelloS uses agents to perform approved tasks. The first implemented execution path uses ACP-compatible local agents over stdio.

## Goal

CelloS should manage task state, approval, dependencies, and scheduling. Agents should handle the actual research, implementation, verification, or other role-specific work.

## Terminology

- **Agent**: an AI/tooling identity that can do work.
- **Connector**: CelloS code that knows how to call a specific agent runtime.
- **ACP layer**: the stable CelloS execution entry point in `cellos/acp.py`.
- **Background process**: the implementation detail CelloS uses to run a task asynchronously from the CLI.

Use `agent` in user-facing docs and UI wherever possible. `worker` may still appear in internal command names or code while the MVP is evolving.

## Agent Catalog

Configuration points to an available agent catalog. The catalog does not hard-code role-to-agent assignment.

Runtime config:

```json
{
  "agents": {
    "default": "opencode",
    "catalog_path": "agentcatalog.json"
  },
  "prompts": {
    "profiles_path": "promptprofiles.json"
  }
}
```

Agent catalog:

```json
{
  "available": {
    "fake": {
      "connector": "fake_acp",
      "description": "Fake development agent"
    },
    "opencode": {
      "connector": "opencode",
      "description": "OpenCode local ACP agent"
    }
  }
}
```

## Connector Architecture

Connectors implement the interface between CelloS and an agent runtime. Each connector knows:

- how to invoke the agent (command, arguments, environment),
- how to send prompts and receive responses,
- how to handle timeouts and errors.

The connector layer isolates CelloS from agent-specific details. New agents are added by writing a new connector, not by modifying the core engine.

## Runtime Behavior

When `cellos run` schedules a task:

1. `SchedulerService` selects work and marks it `in_progress`.
2. `WorkerSpawner` starts a detached subprocess: `python -m cellos.cli worker TASK_ID --mode planning|execution`.
3. The subprocess loads the task, builds a prompt, and calls the configured connector.
4. The connector invokes the agent runtime (e.g., OpenCode, Codex).
5. The agent produces output, which is captured as a `TaskResult`.
6. `PlanningService` or `ExecutionService` saves the result and updates the task.
7. The subprocess exits.

Each background agent run creates a `task_attempts` record. The attempt captures the selected agent, connector, mode, prompt snapshot, result/error summary, and worker log path.

## Debugging

Set `worker.debug_log_path` in config to capture raw ACP protocol logs:

```json
{
  "worker": {
    "backend": "acp",
    "debug_log_path": ".cellos/logs/acp-debug.log"
  }
}
```

## See Also

- `cellos/acp.py` — ACP execution entry point
- `cellos/acp_worker.py` — Worker runtime that calls ACP
- `cellos/connectors/` — Connector implementations
- `docs/architecture.md` — runtime flows
