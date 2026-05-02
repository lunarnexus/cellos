# CelloS Docs

This folder contains the clean CelloS design docs. Treat these docs as the current planning source of truth while the older `docs/` folder remains reference material.

## Current Canonical Docs

- `product.md`: product vision, principles, goals, non-goals, and future features.
- `roles-and-lifecycle.md`: canonical roles, task lifecycle, approvals, change requests, and attention metadata.
- `heartbeat.md`: one-turn scheduler behavior for `cellos run`.
- `communication.md`: proposals, reports, approval requests, comments, and task communication artifacts.
- `pm-adapters.md`: PM-neutral adapter contract.
- `trello.md`: Trello-specific mapping onto the PM adapter model.
- `acp.md`: worker execution through ACP and related runtime rules.
- `implementation-plan.md`: staged build plan.

## Core Decisions

- CelloS is an orchestration layer, not a new coding agent.
- The scheduler/orchestrator is deterministic code.
- AI roles are task execution identities: `coordinator`, `researcher`, `architect`, `engineer`, and `tester`.
- Every meaningful action requires an approved proposal unless a later explicit auto-approval policy says otherwise.
- `cellos run` is one heartbeat, not a forever loop.
- PM tools are user interfaces and sync surfaces. CelloS keeps canonical project state locally.
- Trello is the first PM adapter target.

## Working Rule

When docs conflict, prefer this folder over older docs. If `roles-and-lifecycle.md` conflicts with any other new doc, prefer `roles-and-lifecycle.md` until the conflict is resolved.
