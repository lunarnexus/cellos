# Vikunja Connector Smoke Test

Simple bidirectional smoke test for the real Vikunja connector.

This test proves the two core connector behaviors first:
- Cellos -> Vikunja push works
- Vikunja -> Cellos pull works

This is connector-specific and intentionally mutates the dedicated Vikunja test project.

---

## Scope

This smoke test verifies:
- `cellos init` creates the local baseline if the generic smoke test was not run first
- `cellos pmcon status vikunja` reports a configured Vikunja integration
- a task created in Cellos can be pushed to Vikunja
- a task created in Vikunja can be pulled into Cellos
- a comment added on one side can sync to the other without duplicating on repeat sync

This smoke test does not verify:
- daemon scheduling
- planning
- approval
- execution
- child-task orchestration

Those belong in a deeper integration test.

---

## Authoritative behavior this test assumes

These expectations are grounded in the current implementation:
- `cellos pmcon sync vikunja --push` pushes local tasks to the configured Vikunja project.
- `cellos pmcon sync vikunja --pull` imports unmapped remote tasks from the configured Vikunja project into Cellos.
- Vikunja pull is project-scoped.
- New remote tasks labeled `architect` import as Cellos architect tasks.
- New remote tasks labeled `engineer` import as Cellos engineer tasks.
- If no recognized role label is present, imported tasks default to `engineer`.
- The daemon is not required for manual push/pull sync.

Sources in repo:
- `cellos/cli.py`
- `cellos/integrations/vikunja/provider.py`
- `cellos/integrations/vikunja/client.py`
- `README.md`

---

## Prerequisites

- Python 3.12+
- run from the repo root:

```bash
cd ~/workspace/cellos
```

Required config:
- Vikunja provider enabled
- correct `project_id`
- correct `view_id`
- working `bucket_map`
- valid `VIKUNJA_BASE_URL`
- valid `VIKUNJA_API_TOKEN`

Recommended:
- use a dedicated Vikunja test project
- use unique smoke-test titles so verification is obvious

Example title prefix:
- `[vikunja smoke YYYY-MM-DD HH:MM]`

---

## Process

You are a tester only. You are READ-ONLY with respect to the Cellos codebase.
You may mutate the dedicated Vikunja test project only where this smoke test explicitly tells you to do so.
Do not install, change, or fix code, configuration, credentials, environment variables, test steps, timeouts, local state, or remote project structure unless the user explicitly approves it outside this document.

For every step, follow this exact loop:
1. Display the next step number, the exact command(s) or manual action(s), and the expected outcome.
2. Stop and wait for explicit user approval before doing anything for that step.
3. Run only that step. Do not combine multiple steps. Do not skip ahead.
4. Display the actual result for that step.
5. Compare the actual result against the expected outcome and state PASS or FAIL.
6. If the step FAILS, stop immediately.
7. After a failure, do not retry, do not debug, do not repair, do not change the system, and do not continue to the next step unless the user explicitly tells you what to do next.
8. If the step PASSES, display the next step and wait again for explicit user approval.

Additional rules:
- Never barrel through later steps after an error.
- Never treat a failure as permission to improvise or fix things.
- Direct changes in Vikunja must be made in the browser UI, not through the API, curl, ad hoc scripts, or undocumented shortcuts, unless the user explicitly approves that approach.
- When in doubt, stop and ask.

---

## Step 1: Initialize local Cellos state

Run the local initializer with overwrite so the local database is reset before the test starts, even if a previous smoke run left state behind.

```bash
cellos init --overwrite
```

**Expected:**
- config/bootstrap files exist locally
- local database is recreated from a clean state
- existing `.env` is preserved
- command succeeds without needing the daemon

---

## Step 2: setup the Vikunja integration

```bash
cellos pmcon setup vikunja --clean
```

**Expected:**
- command succeeds
- configured project and view are valid
- baseline bucket structure is present

---

## Step 3: Verify reusable labels in Vikunja

Open the configured Vikunja project in the browser UI and verify the reusable labels required by the connector are available.

The URL is: http://10.1.3.35:3456/. Do NOT use the API; use the browser and navigate with browser_* tools.

**Expected in Vikunja:**
- reusable label `architect` exists
- reusable label `engineer` exists

---

## Step 4: Verify the Vikunja integration is configured

```bash
cellos pmcon status vikunja
```

**Expected:**
- command succeeds
- provider is `vikunja`
- credentials are reported as configured
- target/project info is shown

---

## Step 5: Prove Cellos -> Vikunja push

### 5a. Create a local Cellos task

```bash
cellos add-task "[vikunja smoke YYYY-MM-DD HH:MM] Local push test" -d "Created in Cellos to verify push into Vikunja." -r engineer
cellos status
```

**Expected in Cellos:**
- the new task appears in local status output
- the task has a visible local task ID

### 5b. Push to Vikunja

```bash
cellos pmcon sync vikunja --push
```

**Expected in Cellos:**
- push completes successfully
- sync reports at least one created or updated item
- if this is the first push for the task, exactly one corresponding task should exist in Vikunja after verification

### 5c. Verify in Vikunja

Open the configured Vikunja project in the browser and confirm the task created in Step 5a exists there.

The URL is: http://10.1.3.35:3456/.  Do NOT use the API, you MUST use the browser and navigate with browser_* tools.

**Expected in Vikunja:**
- the task title matches the Cellos task title
- the task description matches the Cellos task description
- the task appears in the configured project
- the task is visible in the expected bucket for its current Cellos status

### 5d. Update the Cellos task and push again

Use the local task ID from Step 5a.

```bash
cellos update <PUSHED_TASK_ID> --details "Updated in Cellos to verify Vikunja reflects task edits."
cellos pmcon sync vikunja --push
```

**Expected in Cellos:**
- update succeeds
- push completes successfully

### 5e. Verify the update in Vikunja

Refresh the same Vikunja task in the browser.

**Expected in Vikunja:**
- the same task still exists once, with no duplicate created
- the description now matches the updated Cellos description

---

## Step 6: Prove Vikunja -> Cellos pull

### 6a. Create a remote Vikunja task

Create a task directly in Vikunja in the browser with:
- title: `[vikunja smoke YYYY-MM-DD HH:MM] Remote pull test`
- description: `Created in Vikunja to verify pull into Cellos.`
- label: `architect`
- bucket: `To-Do`

**Expected in Vikunja:**
- task exists in the configured project
- label `architect` is attached
- task is visible before running pull

### 6b. Pull into Cellos

```bash
cellos pmcon sync vikunja --pull
cellos status
```

**Expected in Cellos:**
- pull completes successfully
- the remote task appears in local status output
- the imported task is present after pull without running the daemon
- existing synced tasks are not duplicated locally

### 6c. Verify imported local details

Identify the imported task ID from `cellos status`, then inspect it:

```bash
cellos detail <PULLED_TASK_ID>
```

**Expected in Cellos:**
- title matches the Vikunja task title
- details/description match the Vikunja task description
- role is `architect`
- status is consistent with the Vikunja bucket

Note:
- a local Cellos `draft` task pushed into Vikunja `To-Do` may later appear locally as `approved` after pull; that is current connector status-normalization behavior and is not by itself a smoke-test failure

### 6d. Re-run pull to verify idempotence

```bash
cellos pmcon sync vikunja --pull
cellos status
```

**Expected in Cellos:**
- pull completes successfully
- no duplicate local task is created for the same Vikunja remote task
- previously imported and previously pushed tasks remain singular in local status output

---

## Step 7: Prove comment sync remains idempotent

Use the pushed local task ID from Step 5a.

### 7a. Add a local Cellos comment and push

```bash
cellos comment <PUSHED_TASK_ID> -m "Smoke-test local comment to verify Vikunja sync."
cellos pmcon sync vikunja --push
```

**Expected in Cellos:**
- comment command succeeds
- push completes successfully

### 7b. Verify the comment in Vikunja

Refresh the already-synced task in the Vikunja browser UI.

**Expected in Vikunja:**
- the new comment is visible on the same task
- the comment appears exactly once

### 7c. Re-run push to verify no duplicate outbound export

```bash
cellos pmcon sync vikunja --push
```

**Expected in Cellos:**
- push completes successfully

**Expected in Vikunja:**
- the same comment still appears exactly once

### 7d. Add a remote Vikunja comment and pull

In the Vikunja browser UI, add a new comment to the same task, then run:

```bash
cellos pmcon sync vikunja --pull
cellos detail <PUSHED_TASK_ID>
```

**Expected in Cellos:**
- pull completes successfully
- the Vikunja comment appears in local task details/comments
- the remote comment appears exactly once

### 7e. Re-run pull to verify no duplicate inbound import

```bash
cellos pmcon sync vikunja --pull
cellos detail <PUSHED_TASK_ID>
```

**Expected in Cellos:**
- pull completes successfully
- the same Vikunja comment still appears exactly once

## Troubleshooting

| Symptom | Likely cause | What to check |
|---|---|---|
| `cellos pmcon status vikunja` shows missing credentials | Vikunja env vars are not available to the CLI | Confirm `VIKUNJA_BASE_URL` and `VIKUNJA_API_TOKEN` are set in the environment Cellos is running with |
| Push succeeds but task is not visible in Vikunja | Wrong project/view config or stale UI view | Confirm the configured project, refresh Vikunja, and check the right project/view |
| Pull succeeds but remote task does not appear in Cellos | Task was created in the wrong Vikunja project or pull was run before saving the remote task | Confirm the task exists in the configured project, then run `cellos pmcon sync vikunja --pull` again |
| Imported role is wrong | Missing or incorrect Vikunja label | Confirm the task has label `architect` or `engineer` before pull |
| Tester expects background automation | Confusing connector sync with orchestration | This smoke test does not require `cellos run`; use manual `--push` and `--pull` sync only |
