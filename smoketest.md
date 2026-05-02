# CelloS Smoke Test

This smoke test verifies the current local MVP behavior:

- config and database initialization,
- draft task planning,
- approved task execution,
- async background workers,
- fake ACP worker calls,
- task status updates,
- task event history.

Run commands from the project root:

```bash
cd /Users/james/Scripts/CelloS/cellos
```

Do not run this through a filesystem sandbox. Use the normal project directory so background workers can read the local config, write the local SQLite database, and run the fake ACP process.

## 1. Run Pytests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_config.py tests/test_models.py tests/test_db.py tests/test_acp_worker.py tests/test_heartbeat.py tests/test_cli.py
```

Expected result:

```text
32 passed
```

## 2. Reset Local State

```bash
cellos init --hard-reset
```

Expected output:

```text
Initialized database at .cellos/cellos.sqlite
Initialized config at /Users/james/.cellos/config.json
```

The default config should use fake ACP:

```json
"worker": {
  "backend": "acp",
  "command": ["python3", "tests/fakes/acp_server.py"],
  "debug_log_path": ".cellos/acp-debug.log"
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
task-...: scheduled planning - Plan smoke test work
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
```

## 4. Smoke Test Approved Execution

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
task-...: scheduled execution - Execute smoke test work
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

## 5. Useful Debug Files

Local runtime files live under:

```text
.cellos/
```

Useful files:

```text
.cellos/cellos.sqlite
.cellos/acp-debug.log
.cellos/worker-task-*.log
```

Empty worker logs are normal when the fake ACP worker succeeds without stderr/stdout outside the ACP protocol.
