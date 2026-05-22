# CelloS Smoke Test

Sequential validation flow covering the complete CelloS system.
Each step must pass before proceeding to the next.

**Prerequisites:**
- Python 3.12+ installed
- `pip install -e ".[dev]"` completed
- Working directory: `cellos/`

---

## Step 1: Unit Tests

Run the full test suite to verify all code is working.

```bash
cd ~/workspace/cellos
python3 -m pytest tests/ -q
```

**Expected:** All tests pass.

**Troubleshooting:**
| Symptom | Fix |
|---------|-----|
| Import errors | Run `pip install -e ".[dev]"` |
| Test failures in specific module | Check that module's implementation matches test expectations |

---

## Step 2: CLI Entry Point

Verify the CLI is installed and responds to help.

```bash
cellos --help
```

**Expected:** Shows command group with all subcommands listed: init, add-task, status, detail, approve, comment, events, update, plan, execute, worker, run.

---

## Step 3: Initialize

Create config files and database.

```bash
rm -rf ~/.cellos
cellos init
cellos status
```

**Expected:**
- Config written to `~/.cellos/` (config.json, agentcatalog.json, promptprofiles.json)
- Database initialized at `~/.cellos/cellos.sqlite`
- Status shows "No tasks found"

---

## Step 4: Create Task

Create a task and verify it appears.

```bash
TASK_ID=$(cellos add-task "Count the number of lines in ~/workspace/cellos/README.md and report back" -d "Count lines and report your findings" -r architect | grep -oP 'Created task \K[^:\s]+')
cellos status
```

**Expected:** Task created with ID, role=architect, status=draft. Status table shows the task.

---

## Step 5: Plan Task

Generate a plan via agent (opencode).

```bash
cellos plan $TASK_ID
```

**Expected:** "Plan generated for <id>", Status: needs_approval.

---

## Step 6: Task Detail

View full task information.

```bash
cellos detail $TASK_ID
```

**Expected:** Panel showing title, status=needs_approval, role, type, details, plan text, and ⚠️ attention marker.

---

## Step 7: Events

View audit trail.

```bash
cellos events $TASK_ID
```

**Expected:** Chronological events including task_created, planning_saved, status_changed.

---

## Step 8: Approve Task

Human gate: approve the plan for execution.

```bash
cellos approve $TASK_ID
```

**Expected:** "✓ Approved task <id>", Status: approved (parent waits for children to complete).

---

## Step 9: Verify Result

Confirm final task state.

```bash
cellos detail $TASK_ID
```

**Expected:** Status: approved (waiting for child tasks to complete). If the architect created child tasks and they complete, the parent auto-transitions to done.

---

## Step 9a: Parent Completion (with child tasks)

If the architect plan created child tasks, verify parent completion:

```bash
# After children complete via execution
cellos detail $TASK_ID
```

**Expected:** Status: done (all child tasks completed successfully).
If any child failed, status shows ⚠️ attention with reason child_failed.

---

## Step 9b: Engineer Execution (optional)

To test execution, create an engineer task with a concrete plan:

```bash
ENG_ID=$(cellos add-task "Count lines in README.md" -d "Use wc -l to count lines" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos approve $ENG_ID  # Engineer tasks need approval without planning — requires 'ready' command (future)
cellos execute $ENG_ID
cellos detail $ENG_ID
```

**Expected:** Task executed, status: done, with result summary.

---

## Step 11: Comments & Attention

Add comment and verify attention triggers.

```bash
COMMENT_TASK_ID=$(cellos add-task "Task for comment test" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos comment $COMMENT_TASK_ID -m "Please use approach X"
cellos status
```

**Expected:** Comment added, ⚠️ attention marker visible in status table.

---

## Step 12: Dependencies

Create tasks with dependencies.

```bash
PARENT_ID=$(cellos add-task "Parent task" -r engineer | grep -oP 'Created task \K[^:\s]+')
CHILD_ID=$(cellos add-task "Child task" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos update $PARENT_ID --add-dep $CHILD_ID
cellos detail $PARENT_ID
```

**Expected:** Parent task shows dependency on child in detail view.

---

## Step 13: Invalid Approval Guard

Attempt to approve a draft task (should fail).

```bash
DRAFT_ID=$(cellos add-task "Draft task" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos approve $DRAFT_ID
```

**Expected:** "Error: Cannot approve task in status 'draft'. Must be 'needs_approval'."

---

## Step 14: Empty Update Guard

Attempt to update with no fields (should fail).

```bash
cellos update $DRAFT_ID
```

**Expected:** "Error: No fields specified for update."

---

## Step 15: Daemon Scheduler

Start daemon, verify it picks up work.

```bash
cellos add-task "Daemon test task" -r engineer
cellos run
```

**Expected:** Daemon starts, picks up draft task for planning, fake_acp generates plan, status shows needs_approval.
Press Ctrl+C to stop.

---

## Troubleshooting

| Step | Symptom | Fix |
|------|---------|-----|
| 1 | Import errors | `pip install -e ".[dev]"` |
| 3 | Config not found | Delete `~/.cellos` and re-run `cellos init` |
| 5 | Worker error | Check fake_acp config in agentcatalog.json |
| 8 | Cannot approve | Task must be in needs_approval status |
| 9 | Execution error | Verify task is approved, check agent config |
| 15 | Daemon hangs | Check concurrent_tasks config, verify fake_acp works |
