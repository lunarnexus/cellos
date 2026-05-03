# ACP Agent Execution

CelloS uses agents to perform approved tasks. The first implemented execution path uses ACP-compatible local agents over stdio.

## Goal

CelloS should manage task state, approval, dependencies, and scheduling. Agents should handle the actual research, implementation, verification, or other role-specific work.

## Terminology

- Agent: an AI/tooling identity that can do work.
- Connector: CelloS code that knows how to call a specific agent runtime.
- ACP layer: the stable CelloS execution entry point in `cellos/acp.py`.
- Background process: the implementation detail CelloS uses to run a task asynchronously from the CLI.

Use `agent` in user-facing docs and UI wherever possible. `worker` may still appear in internal command names or code while the MVP is evolving.

## Agent Catalog

Configuration points to an available agent catalog. The catalog does not hard-code role-to-agent assignment.

Runtime config:

```json
{
  "agents": {
    "default": "fake",
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

By default, `cellos init` creates:

```text
~/.cellos/config.json
~/.cellos/agentcatalog.json
~/.cellos/promptprofiles.json
```

The project ships examples:

```text
cellos.config.example.json
agentcatalog.example.json
promptprofiles.example.json
```

Relative `catalog_path` and `profiles_path` values resolve next to the config file.

The default agent is only a fallback. Later, the Coordinator should select or propose agents at runtime based on task needs, available capabilities, and human approval rules.

Each task attempt should record the selected agent and connector for auditability.

## Connectors

`cellos/acp.py` is the stable entry point for CelloS ACP execution. It resolves a configured agent to a connector and asks the connector to prepare an agent invocation.

The connector interface is modeled after the useful boundaries in `acpx`: an agent catalog, explicit working directory, prompt payload, launch mechanics, and normalized result metadata. CelloS does not delegate orchestration to `acpx`; it borrows interface ideas and keeps lifecycle control in CelloS.

Connector vocabulary:

- `PromptEnvelope`: the CelloS-owned prompt text plus mode and metadata.
- `AgentInvocation`: an intent to ask a selected agent to handle one prompt.
- `PreparedAgentInvocation`: connector-prepared runtime details for the agent turn.
- `resolve_launch_command()`: connector hook that returns the process command used to start an ACP agent runtime.
- `prepare_invocation()`: connector hook that adapts an `AgentInvocation` into a `PreparedAgentInvocation`.

`resolve_launch_command()` is runtime plumbing. It should not build or rewrite the task prompt. Prompt construction remains CelloS-owned so approval rules, role instructions, and audit behavior stay consistent across agents.

Prompt profiles live in `promptprofiles.json`. They define role instructions, mode instructions, response sections, and final reporting rules. The generated prompt for a task attempt is stored with the task result/history, but profile templates do not live in the database.

Initial connectors:

- `fake_acp`: local fake agent for tests and smoke tests.
- `opencode`: local OpenCode ACP agent.

Future connectors may include:

- `acpx`,
- OpenClaw,
- Hermes Agent,
- direct connectors for other ACP-compatible agents.

`acpx` should be treated as a connector option, not as the CelloS orchestrator. CelloS owns lifecycle, approvals, task state, scheduling, dependencies, audit trail, and PM sync.

## MVP Execution Model

For MVP, each task attempt uses one agent session:

```text
prepare invocation -> launch agent runtime -> initialize -> create session -> send prompt -> collect result -> close/stop runtime
```

This keeps task attempts isolated and reduces context carryover.

If similar work must be retried after failure or change request, CelloS should create a fresh attempt with a fresh prompt and concise lessons from the previous attempt.

## ACP Flow

Generic flow:

```text
CelloS -> initialize
Agent -> capabilities
CelloS -> session/new
Agent -> session id
CelloS -> session/prompt
Agent -> session/update events
Agent -> final prompt result
CelloS -> session/close
```

## Prompt Construction

The prompt should include:

- role,
- task objective,
- approved scope,
- constraints,
- dependencies or relevant results,
- expected output format,
- change request/reporting rules.

Agents should receive focused context, not the entire project.

## Result Extraction

CelloS should collect worker message chunks as the human-readable result summary. It should ignore reasoning/thought chunks unless explicitly needed for debug.

For structured outputs, CelloS may parse fenced or embedded JSON blocks, but human-readable text remains important for auditability.

## Non-JSON Stdout

Some agent CLIs print banners or plugin messages to stdout before valid ACP JSON. ACP clients may skip and debug-log non-JSON stdout when configured.

This is transport noise, not the same as the worker's actual task answer.

## Timeouts

`worker_timeout_seconds` is an execution timeout for one task attempt. Some tasks may need longer per-task timeouts later.

Timeout handling should:

- cancel/stop the agent runtime where possible,
- record failure or stale state,
- preserve stderr/debug logs,
- avoid blocking unrelated heartbeat work.

## Permissions

Agents may request permission through ACP or through their own local tooling. CelloS must not silently grant dangerous actions. Approval policy is part of the task lifecycle and future permission handling.

## Future Work

Future designs may add:

- long-lived agent sessions,
- active agent status checks,
- role-specific agent profiles,
- multiple backend types,
- richer permission handling,
- usage/cost reporting.
