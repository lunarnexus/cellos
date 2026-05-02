# Implementation Plan

This plan stages implementation around the current docs. Keep work small, testable, and aligned with approval-first behavior.

## Completed Foundation

Implemented:

- canonical roles: `coordinator`, `researcher`, `architect`, `engineer`, `tester`,
- canonical lifecycle statuses,
- task prompt storage,
- attention metadata,
- processing metadata,
- structured change request reports,
- SQLite persistence,
- `cellos init`,
- required config at `~/.cellos/config.json`,
- fake ACP worker default for development,
- ACP worker execution,
- one-turn `cellos run`,
- async background `cellos worker TASK_ID`,
- DB sanity checks that require `cellos init`,
- task events and `cellos events`,
- approved-task execution scheduling,
- draft-task planning scheduling,
- tests for config, models, DB, ACP worker, heartbeat, and CLI.

## Phase 1: Planning Mode Refinement

Goal: make planning useful enough for human approval.

Current behavior:

- `draft` tasks are eligible for planning.
- `needs_approval` tasks are eligible for replanning only when they have attention.
- successful planning stores worker output in the task prompt and returns the task to `needs_approval`.
- `approved` tasks are eligible for execution.

Next work:

- display task prompt/plan clearly in CLI status or a task detail command,
- add a CLI command to approve a planned task,
- add a CLI command to request revision or mark attention,
- make planning prompts role-aware,
- clarify how parent/child planning should create follow-up tasks.

## Phase 2: Approval Gates

Goal: prevent unapproved write actions.

Work:

- enforce approval before task creation by an AI role,
- enforce approval before filesystem or PM writes,
- distinguish planning output from execution output,
- add tests for blocked unapproved work,
- add clear CLI/PM status for tasks waiting on approval.

## Phase 3: ACP Prompt Profiles

Goal: align worker prompts and results with roles.

Work:

- add role-specific prompt templates,
- add planning vs execution prompt templates,
- add expected report formats,
- add change request reporting instructions,
- preserve raw output on parsing/debug failures.

## Phase 4: PM Adapter Contract

Goal: create a PM-neutral adapter boundary.

Work:

- define adapter interfaces for sync, discovery, updates, and task creation,
- store PM sync metadata,
- keep adapter failures isolated,
- write fake adapter tests before Trello.

## Phase 5: Trello MVP

Goal: sync Trello cards into CelloS and push updates back.

Work:

- read board/list/card metadata,
- filter cards by case-insensitive `cellos` label,
- map Trello lists to CelloS states,
- detect human edits/comments/list moves,
- write prompts/results/comments back to cards,
- create child cards only after approved scope allows task creation.

## Phase 6: Documentation Maintenance

Goal: keep docs aligned with implementation.

Work:

- update docs when lifecycle behavior changes,
- keep examples aligned with `cellos.config.example.json`,
- keep implementation plan focused on remaining work,
- avoid preserving obsolete design history in canonical docs.
