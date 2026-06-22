# CelloS Core Smoke Test

Generic validation flow for the CelloS core CLI and provider framework.
This smoke test is intentionally **connector-independent**: it must pass without
any external PM tool or provider credentials.

---

## Scope

This smoke test verifies:

- core CLI entry points
- local config/database initialization
- basic task lifecycle commands
- generic `pmcon` command surface
- provider discovery/listing
- clean failure for unknown providers

This smoke test does **not** verify any specific connector. Use a
separate connector smoke test for that when a real provider exists.

---

## Prerequisites

- Python 3.12+
- test/dev dependencies installed for the repo
- run from the repo root:

```bash
cd ~/workspace/cellos
```

Optional but recommended first check:

```bash
python3 -m pytest tests/ -q
```

**Expected:** test suite passes (warnings may still be present if documented elsewhere).

---

## Process

You are a tester only.  You are READ-ONLY.  
Do not install, change, or fix test steps, code, timeouts, unless specifically approved in this document.
List each Step, and the expected outcome.  
Optionally pause and wait for user approval to proceed.  
Then run the step, compare with expected outcomes, list the next step and optionally pause for the user.  

---

## Step 1: CLI Entry Point

```bash
cellos --help
```

**Expected:** Help renders and includes `pmcon` in the command list.

---

## Step 2: Initialize Local State

Use an isolated temp directory so the smoke test does not depend on or mutate an
existing real setup.

```bash
export CELLOS_SMOKE_ROOT=$(mktemp -d)
export CELLOS_SMOKE_CFG="$CELLOS_SMOKE_ROOT/.cellos"
export CELLOS_SMOKE_DB="$CELLOS_SMOKE_ROOT/cellos.sqlite"

cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" init --overwrite
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" status
```

**Expected:**
- config files written under `$CELLOS_SMOKE_CFG`
- database initialized at `$CELLOS_SMOKE_DB`
- `status` reports no tasks found

---

## Step 3: Generic `pmcon` Help

```bash
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" pmcon --help
```

**Expected:** shows generic `pmcon` subcommands:
- `list`
- `setup`
- `sync`
- `status`

---

## Step 4: Provider Discovery

```bash
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" pmcon list
```

**Expected:** command succeeds and lists discovered provider(s).

Notes:
- This verifies generic provider discovery.
- It does **not** require provider credentials.
- The exact provider list may grow over time.

---

## Step 5: Unknown Provider Guard

```bash
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" pmcon status doesnotexist
```

**Expected:** command fails cleanly with an unknown-provider error.

---

## Step 6: Create a Local Task

```bash
TASK_ID=$(cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" add-task \
  "Smoke test task" \
  -d "Validate core local CLI behavior" \
  -r architect | grep -oP 'Created task \K[^:\s]+')

cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" status
```

**Expected:**
- task is created
- task appears in `status`
- initial status is `draft`

---

## Step 7: Detail and Events

```bash
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" detail "$TASK_ID"
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" events "$TASK_ID"
```

**Expected:**
- `detail` shows the task record
- `events` includes `task_created`

---

## Step 8: Invalid Approval Guard

```bash
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" approve "$TASK_ID"
```

**Expected:** fails cleanly because a `draft` task cannot be approved.

---

## Step 9: Comment / Attention Path

```bash
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" comment "$TASK_ID" -m "Smoke-test comment"
cellos --config-dir "$CELLOS_SMOKE_CFG" --db "$CELLOS_SMOKE_DB" status
```

**Expected:**
- comment is added
- task remains visible
- attention/comment indicators appear if supported by current UI output

---

## Step 10: Cleanup

```bash
rm -rf "$CELLOS_SMOKE_ROOT"
unset CELLOS_SMOKE_ROOT CELLOS_SMOKE_CFG CELLOS_SMOKE_DB
```

**Expected:** temporary smoke-test files are removed.

---

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `cellos --help` fails | CLI not installed or env not active | reinstall/editable install, verify PATH |
| `init` fails | config example files missing or bad path | inspect `cellos.config.json.example` and `--config-dir` |
| `pmcon list` fails | provider discovery/import problem | inspect `cellos/integrations/registry.py` and provider modules |
| `pmcon status doesnotexist` does not fail cleanly | registry error handling regressed | inspect unknown-provider path in `load_provider()` |
| local task commands fail | DB/config mismatch | verify `--db` and `--config-dir` point to same temp run |
