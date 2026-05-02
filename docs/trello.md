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
- `In Progress`: CelloS is working.
- `Done`: task completed.
- `Cancelled`: task should not be performed.

The adapter owns list-name/list-ID mapping. Core CelloS should not know Trello represents status with lists.

## Labels

The human should only need to add `cellos`.

CelloS may add role/type labels:

```text
coordinator
researcher
architect
engineer
tester
research
build
test
blocked
change-requested
```

Labels are hints and display aids. SQLite remains canonical for task state.

## Members

Do not create fake Trello users for CelloS roles. Roles are CelloS metadata, not Trello identities.

Trello members remain real human users or future service accounts.

## Card Description

The card description should hold the current proposal or approved plan.

Suggested shape:

```md
## Objective

## Proposed Actions

## Scope

## Dependencies And Assumptions

## Success Criteria

## Approval Request
```

Humans may edit the description directly. Description edits are human change signals unless CelloS made the edit and metadata confirms it.

## Comments

Use comments for:

- human revision requests,
- CelloS status updates,
- result reports,
- change request reports,
- parent/dependency mirrors.

Suggested relationship comments:

```text
CelloS parent: <trello-card-url-or-id>

CelloS depends on:
- <trello-card-url-or-id>
```

## Planning Flow

1. Human creates a card.
2. Human adds `cellos`.
3. Human moves it to `Planning`.
4. CelloS imports or syncs it.
5. CelloS drafts or revises a proposal in the description.
6. CelloS comments that the proposal is ready.
7. CelloS moves the card to `Needs Approval`.
8. Human approves, edits, comments, cancels, or moves it back to `Planning`.

CelloS should not repeatedly process a card in `Planning` unless the card has a new human change or other attention signal.

## Approval Flow

Moving a card to `Approved` means the current proposal is approved.

Once approved, CelloS may perform the approved action:

- conduct approved research,
- create explicitly approved child cards,
- perform approved implementation,
- run approved tests.

If CelloS needs to materially change scope, it must request approval again.

## Task Creation

Generated child cards should be real cards, not checklist items.

Generated child cards should usually start in `Needs Approval`, unless the approved parent proposal explicitly allows a different state.

Each generated card should include:

- `cellos` label,
- role/type labels,
- parent relationship comment,
- dependency comments if applicable,
- proposal or task scope in the description.

## Sync Strategy

Each heartbeat:

1. Sync known Trello-linked cards.
2. Discover new candidate cards from relevant lists.
3. Filter candidate cards for the `cellos` label.
4. Update local task records and sync metadata.
5. Mark attention for human edits, comments, approvals, list moves, cancellations, or relationship changes.

The adapter should avoid passing whole-board context to LLM workers. It may fetch many cards from Trello, but workers should receive only the focused task context they need.
