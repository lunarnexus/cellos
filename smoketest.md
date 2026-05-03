# CelloS Smoke Test

This is a quick happy-path check for the local MVP. It is not a full feature test.

Run commands from the project root:

```bash
cd /Users/james/Scripts/CelloS/cellos
```

Do not run this through a filesystem sandbox. Use the normal project directory so background agents can read config, write SQLite state, and launch local ACP processes.

## 1. Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_config.py tests/test_models.py tests/test_db.py tests/test_pm.py tests/test_acp_worker.py tests/test_heartbeat.py tests/test_cli.py
```

Expected:

```text
55 passed
```

## 2. Fake Agent End-To-End

Reset local state:

```bash
cellos init --hard-reset
```

Set `~/.cellos/config.json` to use the fake agent:

```json
"agents": {
  "default": "fake",
  "catalog_path": "agentcatalog.json"
}
```

Create a draft task:

```bash
cellos add-task "Plan smoke test work" --role coordinator --type proposal --prompt "Create a short plan."
```

Run planning:

```bash
cellos run
sleep 1
cellos detail TASK_ID
```

Expected:

- status is `needs_approval`,
- result includes `fake ACP completed task`.

Approve and execute:

```bash
cellos approve TASK_ID
cellos run
sleep 1
cellos status
```

Expected:

- task status is `done`,
- result includes `fake ACP completed task`.

## 3. OpenCode Planning

Prerequisite:

```bash
which opencode
```

The example config uses OpenCode by default. If needed, confirm `~/.cellos/config.json` says:

```json
"agents": {
  "default": "opencode",
  "catalog_path": "agentcatalog.json"
}
```

Create a draft task:

```bash
cellos add-task "Plan OpenCode smoke test" --role engineer --type implementation --prompt "Plan a tiny harmless docs-only change. Do not edit files during planning."
```

Run planning:

```bash
cellos run
sleep 20
cellos detail TASK_ID
```

Expected:

- status is `needs_approval`,
- plan contains structured sections such as `Objective`, `Proposed Actions`, `Risks`, and `Approval Request`.

## 4. Optional OpenCode Execution

Only run this if you are comfortable with OpenCode editing one harmless file.

Approve and execute the task from section 3:

```bash
cellos approve TASK_ID
cellos run
sleep 30
cellos detail TASK_ID
git diff
```

Expected:

- task status is `done`,
- result contains OpenCode's execution summary,
- `git diff` shows only the intended tiny change.
