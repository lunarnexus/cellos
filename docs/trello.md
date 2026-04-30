# CelloS Trello Adapter Plan

This document describes the Trello-specific project-management adapter. Core CelloS should keep a PM-neutral model for tasks, statuses, roles, parent relationships, dependencies, approval state, and execution state. The Trello adapter translates that model into Trello boards, lists, cards, labels, members, comments, and descriptions.

## Trello Concepts

- **Board**: A project workspace.
- **List**: A workflow column on a board. The Trello adapter maps lists to CelloS task states.
- **Card**: A task or planning item.
- **Label**: A tag on a card. CelloS uses labels for opt-in scope, roles, and task types.
- **Member**: A normal Trello assignee. Do not create fake Trello users for CelloS roles.
- **Comment**: Human/CelloS conversation and relationship notes.
- **Description**: The current editable task request or plan.

Do not use Trello checklists for CelloS child tasks. Checklists cannot move through the approval workflow independently, so every actionable unit should be a card.

## Opt-In Scope

CelloS only examines cards with a case-insensitive `cellos` label.

Accepted examples:

```text
cellos
CelloS
CELLOS
```

Cards without this label are ignored unless a future connector mode explicitly imports them.

## Lists

The MVP Trello board uses these lists:

```text
Inbox
Planning
Needs Human
Approved
In Progress
Done
```

List meanings:

- **Inbox**: New untriaged human cards.
- **Planning**: CelloS may inspect the card and draft or revise a plan.
- **Needs Human**: CelloS is waiting for human approval, clarification, or edits.
- **Approved**: CelloS may perform the approved action.
- **In Progress**: CelloS is actively working on the task.
- **Done**: The task is complete.

The Trello adapter owns list-name/list-ID mapping. Core CelloS should not know that Trello represents status with lists.

## Labels

The human only needs to add the `cellos` label.

If a `cellos` card has no parent and no role label, CelloS infers:

```text
role = conductor
type = decompose/plan
```

CelloS may add role/type labels as it imports or creates cards:

```text
conductor
composer
cello
critic
research
planning
build
verify
blocked
```

Use labels for role/type/status hints, not as the only source of truth. CelloS stores the canonical task state in SQLite.

## Members And Assignment

Do not create Trello users named Conductor, Composer, Cello, or Critic. Those are CelloS roles, not Trello identities.

Trello members remain normal human or service-account assignees. The MVP may run based on `cellos` label + role/type + list state. A future configuration can use a real bot/service account member to indicate CelloS ownership.

## Two-Phase Retrieval

The Trello adapter should avoid loading an entire board into LLM context.

1. Sync known cards first.
   - Use local CelloS mappings to find cards already tracked in SQLite.
   - Refresh their list, labels, description hash, and recent comments/actions.

2. Discover new candidate cards.
   - Fetch cards from relevant lists.
   - Filter locally for cards with the case-insensitive `cellos` label.
   - Ignore cards already tracked.
   - Ignore archived/closed cards.

This keeps large human boards from overwhelming CelloS.

## Idempotency And Attention

CelloS must not process a Planning card repeatedly just because it remains in Planning.

Store Trello sync metadata locally, such as:

```text
trello_card_id
trello_list_id
trello_desc_hash
trello_last_activity_date
trello_last_processed_activity_id
trello_last_cellos_comment_id
```

A `Planning` card is eligible for CelloS planning only if:

- it has the `cellos` label,
- it is new to CelloS, or
- its description changed since CelloS last processed it, or
- its latest relevant comment is from a human and newer than the last processed CelloS activity, or
- its list/label/role/status changed in a way CelloS has not processed.

If CelloS was the last actor and nothing meaningful changed, skip the card.

## Planning Flow

1. Human creates a card in `Inbox` and adds `cellos`.
2. Human moves the card to `Planning`.
3. CelloS imports the card.
4. If no role label exists, CelloS infers and adds `conductor`.
5. CelloS writes or updates the plan in the card description.
6. CelloS comments that the plan is ready for review.
7. CelloS records the processed description/activity metadata.
8. CelloS moves the card to `Needs Human`.

Humans can then:

- edit the description directly,
- add comments with requested changes,
- move the card back to `Planning` for revision,
- move the card to `Approved` to accept the plan.

CelloS only revises a card when it returns to `Planning` with new human signal or a changed description.

## Approval And Execution Flow

Moving a card to `Approved` means:

```text
The human approves the current card description/plan as written.
```

When a parent planning card is approved, CelloS reads the approved plan and may create child cards. Generated child cards should go to `Needs Human` by default so a human can approve them individually.

CelloS executes only cards that are:

- labeled `cellos`,
- in `Approved`,
- mapped to an executable role/type,
- not blocked by dependencies,
- not already completed or in progress.

During execution, the Trello adapter may move cards to `In Progress`, then `Done`, and comment with the result.

## Parent And Dependency Relationships

CelloS stores canonical parent/dependency relationships in SQLite. The Trello adapter mirrors them for readability using comments.

Suggested comment format:

```text
CelloS parent: <trello-card-url-or-id>

CelloS depends on:
- <trello-card-url-or-id>
- <trello-card-url-or-id>
```

Humans may create or edit these comments when inserting cards manually into the CelloS workflow. The Trello adapter can use them to initialize or update local mappings during sync.

## Rework

If a plan is too broad or creates too many proposed tasks, the human should leave the card out of `Approved` and comment with the requested correction, for example:

```text
Reduce this to three tasks and keep the first pass docs-only.
```

Then move the card back to `Planning`. CelloS revises the plan on the next heartbeat.

## Connector Boundary

Trello-specific behavior belongs in the Trello connector:

- Trello API calls
- list-name/list-ID mapping
- label lookup and case-insensitive `cellos` filtering
- card creation and movement
- comments and description updates
- Trello activity/comment idempotency
- Trello card ID to CelloS task ID mapping

Core CelloS should stay PM-neutral and operate on tasks, statuses, roles, dependencies, parent IDs, results, and approval state.
