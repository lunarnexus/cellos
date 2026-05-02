# Product

CelloS is a human-governed AI orchestration system for breaking project work into small, reviewable, executable tasks and routing those tasks to worker agents.

The product goal is not full autonomy. The goal is reliable AI-assisted project execution with clear plans, approval gates, auditability, and small task scopes.

## Vision

CelloS gives a human a project-management interface for coordinating AI work:

- the human creates or approves work,
- CelloS plans and routes work,
- worker agents perform approved tasks,
- results and change requests return to the PM tool,
- the human remains in control.

## Problems CelloS Solves

- Large AI tasks fail because context is too broad.
- Autonomous agents loop or expand scope without permission.
- Existing agent frameworks often lack practical human approval gates.
- PM tools are where humans already manage work, but AI agents usually operate outside them.
- Multi-agent work needs a reliable scheduler, not just a chat transcript.

## Principles

### Human Approval First

Meaningful actions require approval. Planning can draft proposals, but task creation, filesystem writes, command execution, and other non-read-only actions require an approved scope.

### Small Focused Context

Worker agents should receive only the context needed for their task. Failed or changed work should usually start a fresh attempt with a focused prompt, not keep extending a bloated session.

### Deterministic Orchestration

The scheduler, state machine, dependency checks, approval checks, and PM sync logic should be deterministic code. AI roles reason inside approved task boundaries.

### PM Tools Are Interfaces

Trello, Asana, Jira, Notion, and similar tools are user interfaces and sync surfaces. They should not own CelloS orchestration logic.

### Best Effort And Recoverable

One failed task or adapter should not stop unrelated work. Local state should preserve enough information for a later heartbeat to recover or retry sync.

## MVP Scope

The MVP should focus on:

- local SQLite project state,
- one scheduler heartbeat via `cellos run`,
- approval-aware task lifecycle,
- Trello as the first PM adapter,
- ACP worker execution,
- clear docs and tests.

## Non-Goals For MVP

- building a custom execution UI,
- supporting every PM tool at once,
- token/cost accounting,
- complex auto-approval policies,
- long-lived worker pools,
- external task queues,
- multi-project coordination.

## Future Features

Future versions may add:

- auto-approval policies,
- cost tracking,
- escalation dashboards,
- webhook-triggered heartbeats,
- more PM adapters,
- role-specific worker profiles,
- long-running worker status checks,
- project postmortems and lessons learned.
