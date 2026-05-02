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

## In-Scope Work

Each adapter must define how a human marks PM items as visible to CelloS.

For Trello this is a case-insensitive `cellos` label. Other PM tools may use tags, labels, custom fields, folders, or projects.

Items outside CelloS scope must be ignored.

## Known Before New

Each heartbeat should sync known PM-linked tasks before discovering new candidates.

Known tasks may have approvals, comments, dependency changes, or cancellation decisions waiting. New discovery should not starve active work.

## Polling Baseline

Adapters must work with polling. Webhooks can be added later as optimizations.

Polling responsibilities:

- fetch known external items,
- fetch candidate new items,
- compare external metadata to local sync metadata,
- mark attention when meaningful changes are detected.

## Sync Metadata

Each PM-linked task should store metadata such as:

```text
provider
external_task_id
external_url
external_status_id
last_human_change_at
last_ai_change_at
last_observed_external_change_at
last_processed_external_change_at
last_processed_input_hash
```

Adapters may add provider-specific fields as needed.

## Human And AI Changes

Adapters should distinguish human changes from CelloS changes where possible.

Human changes may include:

- description/body edit,
- comment,
- status/list move,
- approval,
- cancellation,
- relationship edit.

CelloS changes may include:

- proposal update,
- status update,
- result comment,
- generated task/card creation.

If the PM tool cannot reliably distinguish the actor, the adapter should use conservative metadata and avoid repeated LLM processing unless the content actually changed.

## Approval

Each adapter must define how approval is represented.

Examples:

- moving an item to an approved state,
- setting a custom approval field,
- applying an approval label,
- clicking an approval action.

The core engine only cares that a task is approved. The adapter translates the PM-specific signal.

## Parent And Dependencies

SQLite remains the canonical source for parent/dependency relationships once tasks are imported.

Adapters should mirror relationships into PM tools for human readability. They may also read human-edited relationship hints during sync.

## Error Handling

Adapter failures should be recorded and isolated where possible. A PM sync failure should not prevent unrelated local tasks from running if local state remains safe.
