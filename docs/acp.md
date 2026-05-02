# ACP Worker Execution

CelloS uses worker backends to perform approved tasks. The first implemented backend uses ACP-compatible local agents over stdio.

## Goal

CelloS should manage task state, approval, dependencies, and scheduling. Worker agents should handle the actual research, implementation, verification, or other role-specific work.

## MVP Execution Model

For MVP, each task attempt uses one worker session:

```text
spawn worker -> initialize -> create session -> send prompt -> collect result -> close/stop worker
```

This keeps task attempts isolated and reduces context carryover.

If similar work must be retried after failure or change request, CelloS should create a fresh attempt with a fresh prompt and concise lessons from the previous attempt.

## ACP Flow

Generic flow:

```text
CelloS -> initialize
Worker -> capabilities
CelloS -> session/new
Worker -> session id
CelloS -> session/prompt
Worker -> session/update events
Worker -> final prompt result
CelloS -> session/close
```

## Prompt Construction

The prompt should include:

- role,
- task objective,
- approved scope,
- constraints,
- dependencies or relevant results,
- expected output format,
- change request/reporting rules.

Workers should receive focused context, not the entire project.

## Result Extraction

CelloS should collect worker message chunks as the human-readable result summary. It should ignore reasoning/thought chunks unless explicitly needed for debug.

For structured outputs, CelloS may parse fenced or embedded JSON blocks, but human-readable text remains important for auditability.

## Non-JSON Stdout

Some worker CLIs print banners or plugin messages to stdout before valid ACP JSON. ACP clients may skip and debug-log non-JSON stdout when configured.

This is transport noise, not the same as the worker's actual task answer.

## Timeouts

`worker_timeout_seconds` is an execution timeout for one task attempt. Some tasks may need longer per-task timeouts later.

Timeout handling should:

- cancel/stop the worker where possible,
- record failure or stale state,
- preserve stderr/debug logs,
- avoid blocking unrelated heartbeat work.

## Permissions

Workers may request permission through ACP or through their own local tooling. CelloS must not silently grant dangerous actions. Approval policy is part of the task lifecycle and future permission handling.

## Future Work

Future designs may add:

- long-lived worker sessions,
- active worker status checks,
- role-specific worker profiles,
- multiple backend types,
- richer permission handling,
- usage/cost reporting.
