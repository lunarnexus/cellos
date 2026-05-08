# CelloS Docs

This folder contains the canonical CelloS design docs. Treat these docs as the current planning and implementation source of truth.

## Current Canonical Docs

- `architecture.md`: module responsibilities, runtime flows, "where do I change X?"
- `product.md`: product vision, principles, goals, non-goals, and future features.
- `roles-and-lifecycle.md`: canonical roles, task lifecycle, approvals, change requests, and attention metadata.
- `heartbeat.md`: scheduler behavior: selection rules, concurrency, result handling.
- `prompting.md`: prompt stack, planning/execution boundaries, and structured task creation.
- `communication.md`: proposals, reports, approval requests, comments, and task communication artifacts.
- `pm-adapters.md`: PM-neutral adapter contract.
- `trello.md`: Trello-specific mapping onto the PM adapter model.
- `acp.md`: worker execution through ACP and related runtime rules.
- `implementation-plan.md`: staged build plan.
- `refactoring-spec.md`: structural refactor plan and service contracts.

## Validation

- `smoketest.md`: smoke test for CLI + service integration (run from project root).

## Core Decisions

- CelloS is an orchestration layer, not a new coding agent.
- The scheduler/orchestrator is deterministic code.
- AI roles are task execution identities: `coordinator`, `researcher`, `architect`, `engineer`, and `tester`.
- Every meaningful action requires an approved proposal unless a later explicit auto-approval policy says otherwise.
- `cellos run` is one heartbeat, not a forever loop.
- PM tools are user interfaces and sync surfaces. CelloS keeps canonical project state locally.
- Trello is the first PM adapter target.

## Working Rule

When docs conflict, prefer `roles-and-lifecycle.md` for lifecycle and approval behavior. Otherwise prefer the most specific doc for the topic.
