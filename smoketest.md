# CelloS Smoke Test

This smoke test verifies the current local MVP behavior:

- config and database initialization,
- draft task planning,
- approved task execution,
- async background workers,
- fake ACP worker calls,
- optional OpenCode ACP planning,
- task status updates,
- task event history.

The easiest path is to run commands from the project root:

```bash
cd /Users/james/Scripts/CelloS/cellos
```

Do not run this through a filesystem sandbox. Use the normal project directory so background workers can read the local config, write the local SQLite database, and run the fake ACP process.

The default fake ACP connector command is package-based:

```bash
python3 -m cellos.connectors.fake_acp
```

That command does not depend on a relative path into `tests/`.

Workdir rules:

- `--workdir PATH` uses `PATH`.
- If the current directory has `.cellos/cellos.sqlite`, the current directory is used.
- Otherwise CelloS uses `~/`, which makes the default DB path `~/.cellos/cellos.sqlite`.

## 1. Run Pytests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_config.py tests/test_models.py tests/test_db.py tests/test_pm.py tests/test_acp_worker.py tests/test_heartbeat.py tests/test_cli.py
```

Expected result:

```text
49 passed
```

## 2. Reset Local State

```bash
cellos init --hard-reset
```

Expected output:

```text
Initialized database at ...
Initialized config at /Users/james/.cellos/config.json
Initialized agent catalog at /Users/james/.cellos/agentcatalog.json
Initialized prompt profiles at /Users/james/.cellos/promptprofiles.json
```

The default config should use the fake agent:

```json
"agents": {
  "default": "fake",
  "catalog_path": "agentcatalog.json"
},
"prompts": {
  "profiles_path": "promptprofiles.json"
}
```

The default agent catalog should include both `fake` and `opencode`:

```json
{
  "available": {
    "fake": {
      "connector": "fake_acp",
      "description": "Fake development agent"
    },
    "opencode": {
      "connector": "opencode",
      "description": "OpenCode local ACP agent"
    }
  }
}
```

The default prompt profiles should include planning output sections:

```json
"planning": {
  "output_sections": [
    "Objective",
    "Proposed Actions",
    "Files/Systems Affected",
    "Risks",
    "Acceptance Criteria",
    "Approval Request"
  ]
}
```

## 3. Smoke Test Planning Mode

Create a draft task:

```bash
cellos add-task "Plan smoke test work" --role coordinator --type proposal --prompt "Create a short plan."
```

Run one heartbeat:

```bash
cellos run
```

Expected output:

```text
<ID>: scheduled planning - Plan smoke test work
```

Wait briefly for the background worker:

```bash
sleep 1
```

Check status:

```bash
cellos status
```

Expected result:

- task status is `needs_approval`,
- result text includes `fake ACP completed task`.

Inspect the planned task:

```bash
cellos detail TASK_ID
```

Expected result:

- full prompt/plan text is visible,
- recent events include `planning_saved`.

Optionally revise the planned task before approval:

```bash
cellos update TASK_ID --prompt "Human-approved revised plan text."
cellos detail TASK_ID
```

Expected result:

- the revised prompt is visible,
- recent events include `updated`.

Approve the planned task:

```bash
cellos approve TASK_ID
```

Expected output:

```text
Approved <ID>: Plan smoke test work
```

Check events:

```bash
cellos events
```

Expected event trail includes:

```text
created
status_changed
worker_spawned
worker_started
planning_saved
approved
```

## 4. Smoke Test Approved Execution

Run one heartbeat to execute the approved planned task:

```bash
cellos run
```

Expected output:

```text
<ID>: scheduled execution - Plan smoke test work
```

Wait briefly for the background worker:

```bash
sleep 1
```

Check status:

```bash
cellos status
```

Expected result:

- task status is `done`,
- result text includes `fake ACP completed task`.

## 5. Smoke Test Direct Approved Execution

Create an approved implementation task:

```bash
cellos add-task "Execute smoke test work" --status approved --role engineer --type implementation --prompt "Return a short success message."
```

Run one heartbeat:

```bash
cellos run
```

Expected output:

```text
<ID>: scheduled execution - Execute smoke test work
```

Wait briefly for the background worker:

```bash
sleep 1
```

Check status:

```bash
cellos status
```

Expected result:

- execution task status is `done`,
- result text includes `fake ACP completed task`.

Check events:

```bash
cellos events
```

Expected event trail for the execution task includes:

```text
created
status_changed
worker_spawned
worker_started
result_saved
```

## 6. Useful Debug Files

Local runtime files live under:

```text
.cellos/
```

Useful files:

```text
.cellos/cellos.sqlite
.cellos/logs/acp-debug.log
.cellos/logs/worker-*.log
```

Empty worker logs are normal when the fake ACP worker succeeds without stderr/stdout outside the ACP protocol.

## 7. Optional Real Agent Execution With OpenCode

This test verifies that CelloS can route a planning task and approved execution task through the real OpenCode ACP connector.

Prerequisite:

```bash
which opencode
```

Expected result:

```text
/Users/james/.opencode/bin/opencode
```

Reset local state from the example files:

```bash
cellos init --hard-reset
```

Edit `~/.cellos/config.json` and set:

```json
"agents": {
  "default": "opencode",
  "catalog_path": "agentcatalog.json"
}
```

Confirm `~/.cellos/agentcatalog.json` contains:

```json
"opencode": {
  "connector": "opencode",
  "description": "OpenCode local ACP agent"
}
```

Create a tiny harmless draft task:

```bash
cellos add-task "Add harmless real-agent smoke note" --role engineer --type implementation --prompt "Plan a tiny harmless docs-only change: add one short sentence to suggestions.md noting that the real-agent smoke test reached execution. Do not edit files during planning."
```

Run one heartbeat:

```bash
cellos run
```

Expected output:

```text
<ID>: scheduled planning - Add harmless real-agent smoke note
```

Wait for the background agent process:

```bash
sleep 20
```

Inspect the task:

```bash
cellos detail TASK_ID
```

Expected result:

- task status is `needs_approval`,
- prompt/result contains a real OpenCode-generated plan with structured sections,
- recent events include `planning_saved`.

Approve the plan:

```bash
cellos approve TASK_ID
```

Run one heartbeat to execute:

```bash
cellos run
```

Expected output:

```text
<ID>: scheduled execution - Add harmless real-agent smoke note
```

Wait for the background agent process:

```bash
sleep 30
```

Inspect the task:

```bash
cellos detail TASK_ID
```

Expected result:

- task status is `done`,
- result contains OpenCode's execution summary,
- recent events include `result_saved`.

Review the file diff before committing anything:

```bash
git diff -- suggestions.md
```

If the task remains `in_progress`, check:

```bash
cellos detail TASK_ID
tail -120 .cellos/logs/worker-TASK_ID.log
tail -120 .cellos/logs/acp-debug.log
```
