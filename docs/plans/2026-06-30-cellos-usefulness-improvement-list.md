# CelloS Usefulness Improvement List

> **For Hermes:** This is a high-level feature/action list, not an implementation plan. Do not implement from this document directly. Use it as prioritization input before assigning specific planning/coding tasks.

**Goal:** Make CelloS genuinely useful before adding broad features.

**Current priority:** Execution reliability first, then task planning/decomposition quality.

**Context:** We are analyzing Hermes `/goal` and Hermes Kanban source code only to extract ideas, techniques, methodology, and features. We do not want to use `/goal` or Hermes Kanban directly.

---

## Guiding Principle

CelloS already has the bones: task flow, planning, decomposition, worker execution, daemon scheduling, dependencies, approval gates, and PM sync. The next work should make those bones useful and reliable before adding optional features.

Avoid complexity for its own sake. Add complexity only when it solves a demonstrated CelloS workflow problem.

---

## High-Level Feature and Action List

### 0. Current issue backlog overlaps

**Priority:** Immediate triage input

Fold the known `issues.md` findings into this improvement track instead of treating them as isolated Vikunja cleanup.

Current overlaps:
- `cellos/prompt_builder.py:8:16: F821 Undefined name PromptProfilesConfig` overlaps directly with planning reliability. Resolve or explicitly explain this before deep planning-mode work.
- Vikunja comment push reporting says `Items updated: 0` even when a local comment was exported successfully. This is a concrete reporting need, not abstract metadata bloat.
- Vikunja pull can normalize a local pushed `draft ⚠️` task to `approved`. Audit this before relying on daemon-driven automation, because sync may make work executable.
- Local display strips bracketed smoke-test title prefixes. Decide whether this is intended title normalization or a CLI/display bug.
- Vikunja-origin descriptions/comments show raw HTML wrappers in CelloS detail output. Decide whether to preserve, convert on import, strip for CLI display, or document it.

Use `issues.md` as an integration-quality backlog feeding this plan. The most important overlap is prompt-builder reliability; the most user-visible overlap is misleading sync output.

---

### 1. Execution reliability foundation

**Priority:** Highest

Make worker execution dependable under real use.

Actions to explore:
- Harden worker lifecycle behavior.
- Improve failed, hung, and partial worker detection.
- Improve attempt history and error visibility.
- Add explicit recovery paths for failed or stuck work.
- Ensure task state transitions remain correct when execution fails midway.
- Verify execution behavior through real daemon-driven flows, not only manual commands.

Potential commands/features:
- `cellos retry <task_id>`
- `cellos reclaim <task_id>`
- `cellos reassign <task_id> --agent <agent_id>`
- `cellos block <task_id> -m "reason"`
- `cellos unblock <task_id>`

---

### 2. Real-time daemon behavior

**Priority:** Highest

Treat the daemon as the main runtime, not just a test helper or background accessory.

Actions to explore:
- Strengthen daemon behavior around real-time events.
- Move away from turn-based push/pull/task-action workflows where possible.
- Improve live async behavior and test coverage.
- Verify the daemon reacts correctly to human actions, worker completion, dependency updates, and failures.

Test areas:
- Worker completion wakes daemon.
- Human approval wakes daemon.
- Human comments wake daemon or trigger attention correctly.
- Dependency completion unblocks ready work.
- Multiple concurrent tasks respect scheduler limits.
- Worker timeout/failure does not strand tasks silently.
- Provider auto-sync timing behaves predictably.
- Provider sync cannot silently make unsafe work executable without visible audit/output.

---

### 3. Robust planning mode

**Priority:** Very high

Current plan mode is too light. Dial it in until it produces useful, reviewable, actionable task plans.

Actions to explore:
- Fix or explicitly resolve the current `prompt_builder.py` Ruff F821 before planning-mode expansion.
- Improve planning prompts and planner responsibilities.
- Make planning explicitly analyze constraints, success criteria, failure criteria, dependencies, and missing context.
- Produce better decomposition: smaller, focused tasks with clear ownership and review points.
- Validate plans before moving tasks into approval/execution states.
- Support replanning when humans comment or reject a plan.

Desired outcome:
- A top-level task becomes a clear, human-reviewable execution plan.
- Child tasks are useful units of work, not vague LLM confetti.

---

### 4. Acceptance-criteria analysis

**Priority:** Very high

Add a dedicated improvement track for acceptance-criteria quality and checking.

Ideas to extract from Hermes `/goal` source methodology:
- How goal text is evaluated against worker output.
- How an auxiliary judge decides whether work is complete.
- How budget exhaustion or unclear criteria should block for human review.

CelloS-specific goals:
- Analyze whether a task has enough success/failure criteria before planning.
- Identify ambiguous, missing, or contradictory criteria.
- Judge whether a proposed plan satisfies task criteria.
- Judge whether execution results satisfy task criteria.
- Block for human clarification when criteria are insufficient.

Do not use Hermes `/goal` directly. Extract the evaluation technique and adapt it to CelloS.

---

### 5. Human-created child tasks

**Priority:** High

Child tasks should not be created only by LLM structured actions.

Actions to explore:
- Add or improve CLI support for manually creating child tasks.
- Preserve parent/child/dependency relationships cleanly.
- Ensure human-created and agent-created child tasks use the same underlying model.
- Make it easy for a human to decompose a task directly when desired.

Potential command shape:
- `cellos add-task "Child title" --parent <task_id>`
- `cellos add-child <parent_task_id> "Child title" ...`

Exact CLI shape should be decided later.

---

### 6. Planning/decomposition feedback loop

**Priority:** High

Human feedback should improve the plan instead of forcing awkward manual resets.

Actions to explore:
- When a human comments on a draft or `needs_approval` task, route that feedback into replanning.
- Preserve plan revision history.
- Make previous plan, human feedback, and revised plan visible in task detail.
- Avoid starting from scratch blindly when revising plans.

---

### 7. Recovery/operator controls

**Priority:** High

Add practical operator controls as soon as workflow pain demands them.

Actions to explore:
- Design clear recovery semantics before coding commands.
- Make every recovery action auditable in task events.
- Prefer explicit human action over hidden daemon magic.

Candidate commands:
- `cellos retry`
- `cellos reclaim`
- `cellos reassign`
- `cellos block`
- `cellos unblock`
- `cellos runs`
- `cellos tail`

---

### 8. CLI usability improvements

**Priority:** Medium

Add commands as needed, then do a full CLI review later.

Candidate commands/views:
- `cellos inbox` — tasks needing human attention.
- `cellos blocked` — blocked tasks and reasons.
- `cellos ready` — approved/unblocked work ready for daemon execution.
- `cellos review` — tasks needing approval or post-execution review.
- `cellos daemon-status` — daemon health and current workers.
- `cellos recent-failures` — recent failed attempts.

Known output/reporting cleanup from `issues.md`:
- Make comment export visible in `pmcon sync` output, for example with `Comments exported`.
- Make status normalization visible when provider pull changes local status.
- Decide and document/fix title-prefix display normalization.
- Decide and document/fix HTML rendering for provider-origin descriptions/comments.

Save a future task for a full CLI review after the core flow is useful.

---

### 9. Task graph / dependency visibility

**Priority:** Complete

Implemented `cellos graph <task_id>` which shows a visual dependency
graph: parent, dependencies with satisfied/unsatisfied status, children,
blocked tasks with reasons, and dependents. Combined with existing
`cellos tree` and `cellos deps`, this covers the dependency visibility
needs.

Candidate commands now all present:
- `cellos tree <task_id>` — ancestor/descendant tree view
- `cellos graph <task_id>` — visual dependency graph with status
- `cellos deps <task_id>` — direct parent/child/dependency relationships

---

### 10. Agent/profile isolation

**Priority:** Discuss later

Not yet convincing enough to plan.

Actions to explore:
- Analyze Hermes profile/Kanban source for useful techniques.
- Identify whether CelloS actually needs stronger agent isolation.
- Avoid adopting profile-like isolation just because Hermes has it.

Potential questions:
- Does CelloS need separate memory/tool/config identities per agent?
- Or is `agentcatalog.json` enough for now?
- Would isolation improve reliability or just add configuration burden?

---

### 11. Structured handoff metadata

**Priority:** Defer until actual need

Do not add structured result metadata just because Hermes Kanban has it.

Current stance:
- Keep `TaskResult` simple until CelloS has a concrete downstream need.
- Add fields only when they solve real review, retry, PM sync, or parent aggregation problems.

Possible future examples:
- verification commands run
- changed files
- residual risk
- created child task IDs
- retry notes

But defer until needed.

---

### 12. Source-code analysis track

**Priority:** Supporting research

Analyze Hermes `/goal` and Kanban source code for techniques we can adapt.

Focus areas:
- Acceptance checking and judge prompts.
- Goal-loop budget handling.
- Worker lifecycle management.
- Dispatcher/recovery behavior.
- Blocking/unblocking patterns.
- Heartbeat/stale-worker handling.
- CLI monitoring and recovery commands.

Output should be CelloS-specific design notes, not a direct integration plan.

---

## Suggested Near-Term Ordering

0. Triage current `issues.md` overlaps, especially `prompt_builder.py` F821 and misleading sync output.
1. Execution reliability foundation.
2. Real-time daemon behavior and tests.
3. Robust planning/decomposition.
4. Acceptance-criteria analysis.
5. Human-created child tasks.
6. Recovery/operator commands.
7. CLI usability additions as pain appears.
8. Later discussion: agent/profile isolation, richer metadata.

---

## Explicit Non-Goals For Now

- Do not use Hermes `/goal` directly.
- Do not use Hermes Kanban directly.
- Do not copy Hermes architecture wholesale.
- Do not add rich metadata/handoff structures without a demonstrated need.
- Do not prioritize optional CLI polish over making the core task flow reliable and useful.
- Do not make child task creation LLM-only.
