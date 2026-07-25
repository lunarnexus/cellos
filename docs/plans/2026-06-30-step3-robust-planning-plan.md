# Step 3 — Robust planning/decomposition

Source: `docs/plans/2026-06-30-cellos-usefulness-improvement-list.md`

## Goal
Make planning mode produce reviewable, actionable plans with explicit constraint analysis, dependency/context analysis, and better decomposition quality before a task advances.

## Acceptance criteria
- `cellos/prompt_builder.py` no longer fails Ruff F821.
- Planning prompts explicitly surface:
  - success criteria
  - failure criteria / constraints
  - dependencies
  - recent human comments
  - missing-context analysis requirement
  - decomposition/ownership/review-point expectations
- Planning output is validated before moving a task to `needs_approval`.
- Thin or malformed planning results do not silently advance to `needs_approval`.
- Tests cover both:
  - robust planning prompt composition
  - planning-result validation success/failure behavior

## Likely files
- `cellos/prompt_builder.py`
- `cellos/services/planning_service.py`
- `cellos/services/worker_service.py`
- `tests/test_worker.py`
- `tests/test_services.py` or new targeted planning tests

## Smallest high-value slice
1. Fix the F821 typing issue in `prompt_builder.py`.
2. Expand planning prompt construction to include dependency context and explicit planning instructions.
3. Add a planning-result validator with required sections for reviewable plans.
4. Keep invalid plans out of `needs_approval` and mark them for attention.
5. Verify with targeted + full tests, then do correctness/security review.

## Stop conditions
- If current planning output/config structure cannot support section validation cleanly without first changing prompt-profile config semantics, stop and report.
- If validation overlaps too heavily with Step 4 acceptance-criteria judging, keep Step 3 focused on plan structure/quality only and defer criteria sufficiency scoring to Step 4.
