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
- `pipx`
- `cellos` installed and available on `PATH`
- run from the repo root:

```bash
cd ~/workspace/cellos
```

Install the CLI once from the repo checkout:

```bash
pipx install --python python3.12 --editable .
```

Why this install mode:
- `--python python3.12` is required because CelloS requires Python 3.12+
- `--editable` keeps the installed `cellos` command pointing at this working tree, so source edits are picked up without reinstalling
- reinstall only when packaging metadata or dependencies change

Optional but recommended first checks:

```bash
cellos --help
python3 -m pytest tests/ -q
```

**Expected:**
- `cellos --help` succeeds
- test suite passes (warnings may still be present if documented elsewhere)

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

Use the normal default local Cellos path.

```bash
cellos init --overwrite
cellos status
```

**Expected:**
- config files written under `~/.cellos/`
- database initialized at `~/.cellos/cellos.sqlite`
- `status` reports no tasks found

---

## Step 3: Generic `pmcon` Help

```bash
cellos pmcon --help
```

**Expected:** shows generic `pmcon` subcommands:
- `list`
- `setup`
- `sync`
- `status`

---

## Step 4: Provider Discovery

```bash
cellos pmcon list
```

**Expected:** command succeeds and lists discovered provider(s).

Notes:
- This verifies generic provider discovery.
- It does **not** require provider credentials.
- The exact provider list may grow over time.

---

## Step 5: Unknown Provider Guard

```bash
cellos pmcon status doesnotexist
```

**Expected:** command fails cleanly with an unknown-provider error.

---

## Step 6: Create a Local Task

```bash
TASK_ID=$(cellos add-task \
  "Smoke test task" \
  -d "Validate core local CLI behavior" \
  -r architect | grep -oP 'Created task \K[^:\s]+')

cellos status
```

**Expected:**
- task is created
- task appears in `status`
- initial status is `draft`

---

## Step 7: Detail and Events

```bash
cellos detail "$TASK_ID"
cellos events "$TASK_ID"
```

**Expected:**
- `detail` shows the task record
- `events` includes `task_created`

---

## Step 8: Invalid Approval Guard

```bash
cellos approve "$TASK_ID"
```

**Expected:** fails cleanly because a `draft` task cannot be approved.

---

## Step 9: Comment / Attention Path

```bash
cellos comment "$TASK_ID" -m "Smoke-test comment"
cellos status
```

**Expected:**
- comment is added
- task remains visible
- attention/comment indicators appear if supported by current UI output

---

## Step 10: Cleanup

```bash
rm -rf ~/.cellos
```

**Expected:** local smoke-test files are removed.

---

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `cellos --help` fails | CLI not installed or PATH is wrong | rerun `pipx install --python python3.12 --editable .`, verify `cellos` is on `PATH` |
| `init` fails | config example files missing or bad path | inspect `cellos.config.json.example` and `--config-dir` |
| `pmcon list` fails | provider discovery/import problem | inspect `cellos/integrations/registry.py` and provider modules |
| `pmcon status doesnotexist` does not fail cleanly | registry error handling regressed | inspect unknown-provider path in `load_provider()` |
| local task commands fail | DB/config mismatch | verify Cellos is using the expected default local state under `~/.cellos/` |
