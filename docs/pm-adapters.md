# PM Adapters

Project-management adapters connect CelloS to external tools such as Trello, Asana, Jira, Notion, and others.

PM adapters translate between external PM concepts and CelloS task concepts. They should not own core orchestration logic.

## Responsibilities

A PM adapter is responsible for:

- discovering in-scope work,
- syncing known tasks,
- detecting human changes,
- mapping PM statuses to CelloS statuses,
- writing proposals and reports back to the PM tool,
- mirroring parent/dependency relationships for readability,
- preserving PM-specific IDs and sync metadata.

The core engine is responsible for:

- task lifecycle rules,
- approval checks,
- dependency checks,
- attention evaluation,
- worker scheduling,
- result handling.

## Adapter Contract

The MVP adapter contract lives in `cellos/pm.py`.

Adapters should implement `ProjectManagementAdapter` and exchange `PmTaskSnapshot`, `PmDetectedChange`, `PmTaskUpdate`, `PmCreatedTask`, and `PmSyncResult` objects with the core.

## Canonical Concepts

Adapters should map PM-specific objects onto these CelloS concepts:

```text
task
status
role
proposal
approval
comment
parent
dependency
result
attention signal
```

## Adapter Failures

PM adapter failures should be isolated. If a PM sync fails, local-only tasks may still run. The next heartbeat should retry the PM sync.

## See Also

- `docs/trello.md` — Trello-specific mapping
- `cellos/pm.py` — adapter contract
