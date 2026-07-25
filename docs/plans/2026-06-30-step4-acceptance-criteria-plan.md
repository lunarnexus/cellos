# Step 4 — Acceptance-criteria analysis

Source: `docs/plans/2026-06-30-cellos-usefulness-improvement-list.md`

## Goal
Use the richer task metadata already present (`success_criteria`, `failure_criteria`, plan text, human comments) to judge execution outputs more reliably than the current keyword matcher.

## Current gap
`cellos/services/execution_service.py` still decides success mostly from connector `success` or a tiny keyword list. That ignores the task’s explicit acceptance criteria and failure constraints.

## Target slice
1. Add structured acceptance evaluation in execution save path.
2. Prefer explicit connector `success` when provided, but attach a criteria-analysis summary to the stored result.
3. When connector `success` is absent, evaluate execution text against:
   - success criteria
   - failure criteria / constraints
   - obvious ambiguity / missing evidence
4. Keep the first implementation deterministic and local — no new model call yet.
5. Add focused tests for pass / fail / ambiguous cases.

## Likely files
- `cellos/services/execution_service.py`
- `tests/test_services.py`
- possibly `tests/test_integration.py`

## Acceptance criteria
- execution result records include criteria-aware reasoning
- ambiguous outputs remain non-success
- explicit failure-criteria violations force failure
- full test suite still passes
