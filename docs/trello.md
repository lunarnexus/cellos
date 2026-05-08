# Trello Adapter

Trello is the first PM adapter target. This document maps Trello boards, lists, cards, labels, comments, and descriptions onto the PM-neutral CelloS model.

## Trello Concepts

- **Board**: project workspace.
- **List**: workflow column.
- **Card**: task or planning item.
- **Label**: tag on a card.
- **Member**: normal Trello assignee.
- **Description**: current proposal or approved plan.
- **Comment**: discussion, status update, relationship note, or report.

Do not use Trello checklists for CelloS child tasks. Checklist items cannot move independently through approval.

## In-Scope Cards

CelloS only examines cards with a case-insensitive `cellos` label.

Accepted examples:

```text
cellos
CelloS
CELLOS
```

Cards without this label are ignored.

## Lists

Recommended MVP lists:

```text
Inbox
Planning
Needs Approval
Approved
In Progress
Done
Cancelled
```

Mapping:

- `Inbox`: human-created, not yet ready for CelloS.
- `Planning`: CelloS may draft or revise a proposal.
- `Needs Approval`: waiting for human approval, edit, or cancellation.
- `Approved`: approved scope may be processed when dependencies allow.
- `In Progress`: CelloS or human is actively working on the task.
- `Done`: task completed successfully.
- `Cancelled`: task should not be performed.

## Labels

Use Trello labels to mark:

- `cellos` — in-scope card (required)
- `child` — this card is a child task
- `blocked` — this card is blocked by a dependency
- `change-request` — this card has an active change request

## Cards

Each CelloS task maps to one Trello card. The card description holds the current proposal/plan. Comments on the card are stored as task comments.

Parent/child relationships are mirrored as Trello card links or mentions. Dependencies are tracked in CelloS and reflected in card labels or descriptions.

## Sync Behavior

When CelloS syncs with Trello:

1. Read all cards with the `cellos` label.
2. Update local task records with any human changes (title, description, comments, list moves).
3. Push CelloS changes back to Trello (proposal updates, results, comments).
4. Detect attention signals (human edits, comments, list moves).

If PM sync fails, CelloS continues with local-only tasks. The next heartbeat retries the sync.

## See Also

- `docs/pm-adapters.md` — PM adapter contract
- `cellos/pm.py` — adapter implementation
