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

The Coordinator owns top-level project intake and project direction.

Responsibilities:

- Interpret the human request.
- Decide whether more information is needed.
- Create or revise the top-level project plan.
- Decide when to request research.
- Route work to Architects.
- Handle change requests that bubble up from Architects.
- Escalate to the human when the project direction requires judgment.

The Coordinator is not the runtime scheduler. The scheduler/orchestrator is deterministic code. The Coordinator is an AI role used when reasoning, planning, or human-facing project coordination is needed.

### Researcher

The Researcher gathers information and reports findings.

Responsibilities:

- Propose a research approach before doing research.
- Perform approved research.
- Summarize findings clearly.
- Identify uncertainties, sources, assumptions, and follow-up questions.

The Researcher should not create implementation plans, perform filesystem edits, or create new executable tasks unless explicitly approved in its task scope.

The Researcher reports to whichever role requested the research. A Coordinator or Architect may request research directly.

### Architect

The Architect turns approved goals and research into a concrete design or work breakdown.

Responsibilities:

- Create or revise technical plans.
- Decompose approved work into smaller tasks.
- Define task boundaries, dependencies, and acceptance criteria.
- Decide whether additional research is needed.
- Handle change requests from Engineers and Testers.
- Escalate to the Coordinator when scope, goals, or high-level direction need to change.

Task creation is a write action. The Architect may create tasks only when task creation is explicitly approved.

### Engineer

The Engineer performs approved implementation or execution work.

Responsibilities:

- Propose how it will perform its assigned work when a proposal is required.
- Execute approved implementation tasks.
- Make changes only within the approved scope.
- Attempt limited troubleshooting within the approved task boundary.
- Report success, failure, or blockers.
- Request a change when the approved task cannot be completed as written.

The Engineer should not redesign the plan or silently expand scope. If the task is not achievable within its approved scope, it must report back through a change request.

### Tester

The Tester verifies completed or proposed work.

Responsibilities:

- Propose a verification approach when a proposal is required.
- Execute approved tests or reviews.
- Report findings, evidence, and pass/fail status.
- Request a change when the work cannot be verified or the test scope is insufficient.

The Tester should not fix implementation issues directly unless explicitly assigned an Engineer-style task.

## Role Hierarchy

Default hierarchy:

```text
Coordinator
  -> Architect
      -> Researcher
      -> Engineer
      -> Tester
```

Researcher is a support role. It may be called by either Coordinator or Architect when more information is needed.

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

Role-specific behavior should come from:

- role metadata,
- task scope,
- prompt templates,
- configured worker profiles,
- model/tool configuration,
- approval policy.

The core engine should not implement five unrelated agent systems.

## Task Lifecycle

Each task has one primary lifecycle status.

Canonical statuses:

```text
draft
needs_approval
approved
blocked
in_progress
done
failed
change_requested
cancelled
```

Do not attach multiple primary statuses to one task. If CelloS needs extra information, store it as metadata, task events, task results, comments, or attention signals.

### draft

The task or proposal is being created or revised. It is not approved for action.

### needs_approval

The task has a proposal and is waiting for human approval, rejection, or direct revision.

### approved

The human has approved the task's current proposal/scope. The approved action may be scheduled when dependencies are satisfied.

### blocked

The task cannot proceed because a prerequisite is incomplete or an external condition is not met.

### in_progress

The task is currently being worked by a worker.

### done

The task completed successfully and has a recorded result.

### failed

The task attempt failed. A future retry or replacement should be a new task or new attempt with fresh context, not an unbounded loop.

### change_requested

The assigned role concluded that the task cannot be completed as approved and produced a change request report.

### cancelled

The task should not be performed. This is a terminal state for work that the human or system has decided not to pursue.

## Proposal And Approval Model

Every task should have a proposal or plan before it performs meaningful action.

The proposal explains:

- what the task intends to do,
- what files/systems/tools it may touch,
- what output it will produce,
- what success looks like,
- what assumptions or constraints apply.

The human may:

- approve the proposal,
- edit the proposal directly,
- comment with requested changes,
- cancel the task.

Only after approval may the task perform the approved action.

## Task Creation Rules

Creating tasks is a write action.

Task creation is allowed only when:

- the current task is approved, and
- the approved proposal explicitly authorizes creating the specific tasks or class of tasks.

If an Architect wants to create new tasks that were not covered by the approved proposal, it must request approval first.

This prevents uncontrolled task explosions and preserves an audit trail.

## Change Request Flow

A change request is used when a task cannot be completed as approved.

The child task becomes:

```text
change_requested
```

The parent task does not automatically change primary status. Instead, the change request becomes an attention signal for the parent role.

The parent role reviews the change request and decides what to do next:

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

When a task fails or requests a change, that task attempt should usually be treated as closed.

If CelloS reattempts similar work, it should create a new task or new attempt with:

- a fresh worker session,
- a fresh prompt,
- relevant lessons from the previous attempt,
- narrower scope or revised instructions.

This reduces LLM loops and keeps context focused.

## Attention Signals

Task status and task attention are separate concepts.

Status answers:

```text
Where is this task in its lifecycle?
```

Attention answers:

```text
Should CelloS inspect or act on this task during the next heartbeat?
```

Examples of possible attention signals:

- a child task entered `change_requested`,
- a human edited the task proposal,
- a human added a comment,
- a task moved into an approved state,
- a dependency completed,
- an in-progress task exceeded a configured age threshold.

Attention should be stored as durable task metadata. The heartbeat and PM sync process can update this metadata when they detect a new human change, approval, dependency change, child change request, stale task, or other event requiring work.

Minimum attention metadata:

```text
attention_required: true/false
attention_reason: short machine-readable reason
attention_detail: short human-readable explanation
attention_since: timestamp
```

This gives CelloS a clear queue of tasks that need thought or action without using multiple primary statuses.

The exact attention detection and clearing rules will be defined in the heartbeat/system loop design.

## Open Questions For Later

- How should attention signals be stored?
- How does the heartbeat avoid reprocessing the same task when no human or dependency state changed?
- How many troubleshooting turns may an Engineer attempt before reporting failure or requesting a change?
- Which actions can eventually be auto-approved by configuration?
- How should PM tools display approved proposals, change requests, and closed attempts?
