# CelloS Smoke Test

This is a current happy-path smoke test for the local MVP. It is not a full feature test.

Run commands from the project root, where `pyproject.toml` lives.

Do not run this through a filesystem sandbox. Use the normal project directory so background agents can read config, write SQLite state, and launch local ACP processes.

## 1. Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_config.py tests/test_models.py tests/test_db.py tests/test_pm.py tests/test_task_actions.py tests/test_acp_worker.py tests/test_heartbeat.py tests/test_cli.py
```

Expected: all tests pass.

## 2. Reset State

```bash
cellos init --hard-reset
cellos status
```

Expected:

- config files are refreshed in `~/.cellos/`,
- the database is reset in `.cellos/cellos.sqlite`,
- `cellos status` shows no tasks.

The example config uses OpenCode by default. Confirm OpenCode is available:

```bash
which opencode
```

## 3. Basic OpenCode Planning

Create a draft planning task:

```bash
cellos add-task "Plan OpenCode smoke test" --role engineer --type implementation --prompt "Plan a tiny harmless docs-only change. Do not edit files during planning."
```

Run one heartbeat:

```bash
cellos run
sleep 25
cellos status
cellos detail TASK_ID
```

Expected:

- task status is `needs_approval`,
- the plan has sections such as `Objective`, `Proposed Actions`, `Risks`, and `Approval Request`,
- no files are edited.

## 4. Research/Decomposition Loop

Reset again before this larger flow:

```bash
cellos init --hard-reset
```

Create a parent task that must plan, create a research child, then replan with research results:

```bash
cellos add-task "Prototype docs improvement loop" --role architect --type architecture --prompt "Plan a tiny docs-only improvement to smoketest.md. For this prototype, include exactly one prerequisite research child task in the plan. The approved execution of this planning task should create that research child task only. Required child fields: title 'Research smoketest.md improvement', role researcher, task_type research, status approved, blocks_parent true, prompt 'Inspect smoketest.md read-only and report exactly one small useful improvement. Do not edit files.' Do not edit files during planning."
```

Run planning:

```bash
cellos run
sleep 25
cellos detail TASK_ID
```

Expected:

- parent status is `needs_approval`,
- the plan proposes exactly one research child task,
- the plan says no files are edited during planning.

Approve the parent plan and create the research child:

```bash
cellos approve TASK_ID
cellos run
sleep 35
cellos status
cellos detail TASK_ID
```

Expected:

- parent becomes `blocked`,
- one research child is created,
- because `preapprove_research_tasks` defaults to `false`, the child should be `needs_approval`.

Approve and run the research child:

```bash
cellos approve CHILD_TASK_ID
cellos run
sleep 40
cellos status
cellos detail TASK_ID
```

Expected:

- research child becomes `done`,
- parent returns to `draft`,
- parent detail shows a system comment beginning with `Research Results from ...`.

Run parent replanning with the research results:

```bash
cellos run
sleep 30
cellos detail TASK_ID
```

Expected:

- parent status is `needs_approval`,
- the new plan uses the `Research Results` comment,
- no files are edited.

## 5. Optional Final Execution

Only run this if you are comfortable with OpenCode making the approved docs edit.

Approve and run the current parent plan:

```bash
cellos approve TASK_ID
cellos run
sleep 35
cellos detail TASK_ID
git diff
```

Expected:

- task status is `done`, or a child execution task is created depending on the plan,
- any file edit is limited to the approved docs-only scope,
- `git diff` shows only the intended change.
