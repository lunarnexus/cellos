# Structured Communication

CelloS roles communicate through structured artifacts attached to tasks and mirrored into PM tools. These artifacts should be readable by humans and usable by CelloS.

## Goals

- Make every proposed action reviewable.
- Keep PM card/task descriptions useful to humans.
- Keep worker outputs concise enough for higher-level roles.
- Preserve an audit trail of plans, approvals, reports, and change requests.

## Artifact Types

Canonical communication artifacts:

```text
proposal
approval_request
research_report
work_report
test_report
change_request_report
status_update
human_comment
```

## Proposal

Every meaningful task should have a proposal before action.

A proposal should include:

- objective,
- intended actions,
- scope boundaries,
- files/systems/tools expected to be touched,
- dependencies or assumptions,
- success criteria,
- approval request.

Suggested Markdown shape:

```md
## Objective

## Proposed Actions

## Scope

## Dependencies And Assumptions

## Success Criteria

## Approval Request
```

The PM card/task description should contain the current proposal or approved plan. Comments should contain discussion, revision requests, status updates, and historical notes.

## Approval Request

An approval request asks the human to approve a specific scope.

It should be explicit:

```md
Approve this task to:
- create the listed child tasks, or
- perform the listed research, or
- make the listed implementation changes, or
- run the listed verification steps.
```

Approval is not open-ended. If the scope changes materially, CelloS must request approval again.

## Research Report

A research report should include:

- question investigated,
- sources or evidence,
- findings,
- uncertainties,
- recommendation,
- follow-up questions if needed.

Researchers should not create implementation plans unless the task explicitly asks for that.

## Work Report

An Engineer work report should include:

- what was changed or executed,
- files/systems touched,
- commands run if relevant,
- result,
- remaining risks,
- follow-up tasks or verification suggestions.

## Test Report

A Tester report should include:

- what was tested,
- method used,
- pass/fail result,
- evidence,
- defects or concerns,
- recommended next action.

## Change Request Report

Use a change request when a task cannot be completed as approved.

Canonical shape:

```md
## Change Request Report

### Blocker Summary

### Why The Approved Task Cannot Be Completed

### Evidence / Attempted Steps

### Recommended Next Action

### Human Approval Needed
```

The child task enters `change_requested`. The parent receives attention and decides what to do next.

## Status Update

Status updates should be short. They belong in PM comments or task events, not in the main proposal unless they change the current plan.

Examples:

```text
CelloS drafted a proposal and is waiting for approval.
CelloS started approved work.
CelloS completed the task and recorded the result.
CelloS requested a change because the approved scope is insufficient.
```

## Human Comments

Human comments are treated as possible attention signals. CelloS should not assume every comment is an instruction, but a new human comment means the task may need evaluation.

Adapters may preserve comments exactly as written and summarize only when passing context to a worker.

## Machine-Readable Data

Human-readable Markdown is the primary MVP format. CelloS may later add machine-readable blocks for task proposals, dependency lists, or result schemas.

If machine-readable blocks are added, they must not make normal human editing fragile.
