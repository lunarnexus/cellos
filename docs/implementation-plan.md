# Implementation Plan

This plan stages implementation around the new docs. Keep work small, testable, and aligned with approval-first behavior.

## Phase 1: Align Core Models

Goal: update internal models to match the canonical roles and lifecycle.

Work:

- Replace old role names with `coordinator`, `researcher`, `architect`, `engineer`, `tester`.
- Replace old statuses with the canonical lifecycle statuses.
- Add attention metadata.
- Add processing metadata needed for idempotency.
- Keep existing tests passing or update them to the new language.

## Phase 2: Communication Artifacts

Goal: represent proposals, reports, and change requests cleanly.

Work:

- Add fields or helper models for proposal text.
- Add structured report/result shapes where useful.
- Add change request report support.
- Update CLI display to show proposal/result status clearly.

## Phase 3: Heartbeat Semantics

Goal: make `cellos run` behave like one scheduler heartbeat.

Work:

- Load `~/.cellos/config.json` with defaults.
- Support CLI overrides for concurrency and timeout.
- Evaluate attention before worker spawning.
- Skip tasks with no new signal.
- Preserve best-effort behavior.

## Phase 4: PM Adapter Contract

Goal: create a PM-neutral adapter boundary.

Work:

- Define adapter interfaces for sync, discovery, updates, and task creation.
- Store PM sync metadata.
- Keep adapter failures isolated.
- Write fake adapter tests before Trello.

## Phase 5: Trello MVP

Goal: sync Trello cards into CelloS and push updates back.

Work:

- Read board/list/card metadata.
- Filter cards by case-insensitive `cellos` label.
- Map Trello lists to CelloS states.
- Detect human edits/comments/list moves.
- Write proposals/results/comments back to cards.
- Create child cards only after approved scope allows task creation.

## Phase 6: Approval Gates

Goal: prevent unapproved write actions.

Work:

- Enforce approval before task creation.
- Enforce approval before worker execution.
- Add tests for blocked unapproved work.
- Add clear CLI/PM status for tasks waiting on approval.

## Phase 7: ACP Worker Refinement

Goal: align worker prompts and results with new roles.

Work:

- Add role-specific prompt templates.
- Add expected report formats.
- Add change request reporting instructions.
- Preserve raw output on parsing/debug failures.

## Phase 8: Documentation Cleanup

Goal: make `docs2/` the canonical documentation.

Work:

- Review all docs2 files.
- Update project README to point to docs2.
- Archive, remove, or redirect old docs.
- Update HANDOFF.md to reflect the new design.
