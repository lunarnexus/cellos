# Roles And Task Lifecycle

This document defines the canonical CelloS roles, task lifecycle, approval model, and change request behavior. It is PM-neutral: Trello, Asana, Jira, Notion, and other PM tools should map their own concepts onto this model through adapters.

## Canonical Roles

CelloS uses five canonical roles:

```text
coordinator
researcher
architect
engineer
tester
```

Each role is a task execution identity. Mechanically, all roles use the same core agent execution pipeline: CelloS creates a task, builds a prompt from task data and role instructions, sends it to a worker, records the result, and updates project state.

The roles stay explicit because future versions should be able to customize prompts, tools, models, approval policies, and PM labels per role.

### Coordinator

Owns top-level project intake and direction. Interprets human requests, creates/revises project plans, decides when to request research, routes work to Architects, handles change requests from Architects, escalates to the human when project direction requires judgment. Not the runtime scheduler — that is deterministic code.

For MVP, top-level task intake should capture at least:

- a title,
- details or supporting context,
- success criteria,
- failure, avoidance, or constraint criteria.

### Researcher

Gathers information and reports findings. Proposes a research approach, performs approved research, summarizes findings clearly, identifies uncertainties and follow-up questions. Should not create implementation plans, perform filesystem edits, or create new executable tasks unless explicitly approved.

### Architect

Turns approved goals and research into a concrete design or work breakdown. Creates/revises technical plans, decomposes approved work into smaller tasks, defines task boundaries/dependencies/acceptance criteria, handles change requests from Engineers and Testers, and escalates to the Coordinator when scope or goals need to change.

The Architect should usually decompose work unless the task is obviously small and direct. Research may show that a planned task still needs deeper decomposition, more dependencies, or follow-on tasks.

The Architect may ask clarifying questions in task comments/conversation while still producing a plan. Clarification should refine the current plan, not block all planning until every unknown is resolved.

Task creation is a write action — the Architect may create tasks only when explicitly approved.

### Engineer

Performs approved implementation or execution work. Proposes how it will perform its assigned work, executes approved tasks, makes changes only within the approved scope, attempts limited troubleshooting, reports success/failure/blockers, requests a change when the approved task cannot be completed as written. Should not redesign the plan or silently expand scope.

### Tester

Verifies completed or proposed work. Proposes a verification approach, executes approved tests or reviews, reports findings/evidence/pass-fail status, requests a change when the work cannot be verified or the test scope is insufficient. Should not fix implementation issues directly unless explicitly assigned an Engineer-style task.

## Role Hierarchy

```text
Coordinator -> Architect -> {Researcher, Engineer, Tester}
```

Change requests usually move one level up:

```text
Engineer -> Architect
Tester -> Architect
Researcher -> requesting role
Architect -> Coordinator
Coordinator -> Human
```

This keeps change handling local and avoids reopening the entire project when only a small part of the plan needs revision.

## Common Agent Execution Model

All roles share one common execution mechanism:

```text
Task -> prompt builder -> worker backend -> result -> database update -> PM sync
```

Role-specific behavior comes from: role metadata, task scope, prompt templates, configured worker profiles, model/tool configuration, approval policy. The core engine should not implement five unrelated agent systems.

## Task Lifecycle

Each task has one primary lifecycle status.

```text
draft -> needs_approval -> approved -> in_progress -> done
                                       |
                                       v
                                  change_requested
                                       |
                                       v
                                  (revise -> approved -> ...)
```

Additional terminal states: `blocked`, `failed`, `cancelled`.

Do not attach multiple primary statuses to one task. If CelloS needs extra information, store it as metadata, task events, task results, comments, or attention signals.

### Status definitions

| Status | Meaning |
|---|---|
| `draft` | Task/proposal being created or revised. Not approved for action. |
| `needs_approval` | Proposal ready, waiting for human approval, rejection, or direct revision. |
| `approved` | Human approved the current proposal/scope. May be scheduled when dependencies are satisfied. |
| `blocked` | Cannot proceed because a prerequisite is incomplete or an external condition is not met. |
| `in_progress` | Currently being worked by a worker. |
| `done` | Completed successfully with a recorded result. |
| `failed` | Task attempt failed. Retry should be a new task or attempt with fresh context. |
| `change_requested` | Assigned role concluded the task cannot be completed as approved. Produced a change request report. |
| `cancelled` | Should not be performed. Terminal state for work the human or system decided not to pursue. |

## Proposal And Approval Model

Every task should have a proposal or plan before it performs meaningful action.

The proposal explains: what the task intends to do, what files/systems/tools it may touch, what output it will produce, what success looks like, what assumptions or constraints apply.

The human may: approve the proposal, edit the proposal directly, comment with requested changes, cancel the task.

Only after approval may the task perform the approved action.

For MVP, research tasks, engineer/execution tasks, and tester/verification tasks all require a plan and approval before execution. Auto-approval policies are deferred until later.

## Task Creation Rules

Creating tasks is a write action. Task creation is allowed only when:

1. The current task is approved, and
2. The approved proposal explicitly authorizes creating the specific tasks or class of tasks.

If an Architect wants to create new tasks not covered by the approved proposal, it must request approval first. This prevents uncontrolled task explosions and preserves an audit trail.

Subtasks are still normal tasks. They may have a parent, dependencies, and a specialized role or agent assignment. A created subtask may itself need planning, approval, or further decomposition before execution.

## Change Request Flow

A change request is used when a task cannot be completed as approved.

The child task becomes `change_requested`. The parent task does not automatically change primary status. Instead, the change request becomes an attention signal for the parent role.

The parent role reviews the change request and decides:

- revise the plan,
- create a replacement task,
- ask for human approval,
- request more research,
- escalate further upward,
- cancel the work.

This avoids conflicting task statuses while still allowing higher-level roles to respond.

## Change Request Report

A task in `change_requested` should include a structured report:

```text
Change Request Report

Blocker summary:
Why the approved task cannot be completed:
Evidence / attempted steps:
Recommended next action:
Human approval needed:
```

The report should be concise enough for the parent role to use as context without loading the full failed session.

## Closed Task Attempts

When a task fails or requests a change, that task attempt should usually be treated as closed. If CelloS reattempts similar work, it should create a new task or new attempt with a fresh worker session, a fresh prompt, relevant lessons from the previous attempt, and narrower scope or revised instructions. This reduces LLM loops and keeps context focused.

## Attention Signals

Task status and task attention are separate concepts.

- **Status** answers: "Where is this task in its lifecycle?"
- **Attention** answers: "Should CelloS inspect or act on this task during the next heartbeat?"

Examples of attention signals:

- a child task entered `change_requested`,
- a human edited the task proposal,
- a human added a comment,
- a task moved into an approved state,
- a dependency completed,
- an in-progress task exceeded a configured age threshold.

Attention is stored as durable task metadata. The heartbeat and PM sync process update this metadata when they detect a new human change, approval, dependency change, child change request, stale task, or other event requiring work.

Minimum attention metadata:

```text
attention_required: true/false
attention_reason: short machine-readable reason
attention_detail: short human-readable explanation
attention_since: timestamp
```

This gives CelloS a clear queue of tasks that need thought or action without using multiple primary statuses.

The exact attention detection and clearing rules are defined in `SchedulerService` (`cellos/services/scheduler.py`) and the service-oriented runtime notes in `docs/refactoring-spec.md`.

## Open Questions For Later

- How should attention signals be stored?
- How does the heartbeat avoid reprocessing the same task when no human or dependency state changed?
- How many troubleshooting turns may an Engineer attempt before reporting failure or requesting a change?
- Which actions can eventually be auto-approved by configuration?
- How should PM tools display approved proposals, change requests, and closed attempts?
