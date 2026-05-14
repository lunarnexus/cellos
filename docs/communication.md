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

## Reports

Research, work, and test reports should include:

- what was done,
- what was found,
- what succeeded or failed,
- what remains to be done.

Keep reports focused. Higher-level roles should be able to scan reports without reading every detail.

## Comments

Comments and conversation are the clarification channel between the human and the planning role. They are where the Architect can ask questions, the human can answer or revise direction, and CelloS can accumulate the discussion needed to improve the next plan.

Human comments are stored separately from the task prompt/plan. A comment on an unapproved task marks durable attention, which makes the task eligible for replanning. Planning prompts include task comments and research-result system comments. Execution prompts stay focused on the approved plan.

Task intake details, the current plan/proposal, comments/conversation, and execution results should remain conceptually separate even when some UI surfaces present them together.

## See Also

- `docs/roles-and-lifecycle.md` — task lifecycle and change request flow
- `docs/prompting.md` — prompt construction
- `cellos/services/task_service.py` — comment handling
