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
TASK_ID=$(cellos add-task "Count lines and report your findings" -d "Count the number of lines in ~/workspace/cellos/README.md and report back" -r architect | grep -oP 'Created task \K[^:\s]+')
cellos status
```

**Expected:** Task created with ID, role=architect, status=draft. Status table shows the task.

---

## Step 5: Plan Task

Generate a plan via agent (cellos_acp with opencode agent). Planning works for any role — architect decomposes into child tasks, engineer/researcher/tester produce role-specific plans.

```bash
cellos --debug plan $TASK_ID
```

**Expected:** "Plan generated for <id>", Status: needs_approval.

**Debug verification:** With `--debug`, `~/.cellos/debug.log` should include the exact prompt sent from Cellos to cellos-acp and the raw response returned from cellos-acp before Cellos parses or saves it. Look for `cellos-acp request body`, `cellos-acp response metadata`, `cellos-acp response combined body`, and `Planning result raw input`. The default `text_wait` for late ACP text chunks is `2.0` seconds.

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

## Step 10: Child Tasks — Plan, Approve, Execute via Daemon

Verify the full child-task lifecycle: daemon plans children, human approves, daemon executes, parent auto-completes.

```bash
# List child tasks created by the architect (should be in draft status)
cellos status -s draft

# Start daemon in background — it will plan all draft children
# Redirect output to log to avoid interfering with other CLI commands
cellos run --debug > /tmp/cellos_daemon.log 2>&1 &
DAEMON_PID=$!

# Wait for daemon to plan children (draft → needs_approval)
# Adjust sleep if your agent is slower/faster
sleep 5
cellos status -s needs_approval

# Approve all planned children (extract hex task IDs from Rich table output)
for CHILD in $(cellos status -s needs_approval | grep -oP '[0-9a-f]{12}'); do
    cellos approve $CHILD
done

# Wait for daemon to pick up approved children and execute them
sleep 10

# Stop daemon
kill $DAEMON_PID 2>/dev/null
wait $DAEMON_PID 2>/dev/null

# Verify parent auto-completed when all children finished
cellos detail $TASK_ID
```

**Expected:** Children planned (needs_approval), approved, executed by daemon (done). Parent task status: done (all child tasks completed). If any child failed, parent shows ⚠️ attention with reason child_failed.

---

## Step 11: Engineer Plan → Approve → Execute

Test the full engineer task lifecycle: plan, approve, execute.

```bash
# Create an engineer task
ENG_ID=$(cellos add-task "Count lines in README.md" -d "Use wc -l to count lines in ~/workspace/cellos/README.md and report the count" -r engineer | grep -oP 'Created task \K[^:\s]+')

# Plan the engineer task (any role can be planned)
cellos --debug plan $ENG_ID

# Approve the plan
cellos approve $ENG_ID

# Execute the approved plan
cellos execute --debug $ENG_ID

# Verify result
cellos detail $ENG_ID
```

**Expected:** Task planned (needs_approval), approved, executed, status: done with result summary.

---

## Step 12: Comments & Attention

Add comment and verify attention triggers.

```bash
COMMENT_TASK_ID=$(cellos add-task "Task for comment test" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos comment $COMMENT_TASK_ID -m "Please use approach X"
cellos status
```

**Expected:** Comment added, ⚠️ attention marker visible in status table.

---

## Step 13: Comment Revision Flow

Commenting on a `needs_approval` task sends it back to `draft` for re-planning.

```bash
# Create and plan a task
REV_ID=$(cellos add-task "Build a login form" -d "Create a login form with email and password fields" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos --debug plan $REV_ID
cellos detail $REV_ID  # Should show needs_approval

# Comment to request revision
cellos comment $REV_ID -m "Also add a 'Remember me' checkbox"
cellos detail $REV_ID  # Should show draft status

# Re-plan with the comment considered
cellos --debug plan $REV_ID
cellos detail $REV_ID  # Should show needs_approval again, plan includes checkbox
```

**Expected:** After comment, task transitions to `draft`. Re-planning considers the comment and generates an updated plan.

---

## Step 14: Dependencies

Create tasks with dependencies.

```bash
PARENT_ID=$(cellos add-task "Parent task" -r engineer | grep -oP 'Created task \K[^:\s]+')
CHILD_ID=$(cellos add-task "Child task" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos update $PARENT_ID --add-dep $CHILD_ID
cellos detail $PARENT_ID
```

**Expected:** Parent task shows dependency on child in detail view.

---

## Step 15: Invalid Approval Guard

Attempt to approve a draft task (should fail).

```bash
DRAFT_ID=$(cellos add-task "Draft task" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos approve $DRAFT_ID
```

**Expected:** "Error: Cannot approve task in status 'draft'. Must be 'needs_approval'."

---

## Step 16: Empty Update Guard

Attempt to update with no fields (should fail).

```bash
cellos update $DRAFT_ID
```

**Expected:** "Error: No fields specified for update."

---

## Step 17: Daemon Scheduler

Start daemon, verify it picks up work. The daemon only plans (draft → needs_approval) — execution requires manual approval.

```bash
cellos add-task "Daemon test task" -r engineer
cellos run --debug
```

**Expected:** Daemon starts, picks up draft task for planning, generates plan, status shows needs_approval. Execution requires human approval gate.
Press Ctrl+C to stop.

---

## Troubleshooting

| Step | Symptom | Fix |
|------|---------|-----|
| 1 | Import errors | `pip install -e ".[dev]"` |
| 3 | Config not found | Delete `~/.cellos` and re-run `cellos init` |
| 5 | Planning error | Check cellos_acp config in agentcatalog.json |
| 5 | Plan appears truncated or incomplete | Compare `cellos-acp response combined body` with `Planning result raw input` in `~/.cellos/debug.log` to determine whether truncation happened before or after Cellos received the ACP response |
| 8 | Cannot approve | Task must be in needs_approval status |
| 10 | Children not planned | Check daemon output, verify children are in draft status |
| 10 | Children not executed | Verify children were approved, check daemon picked them up |
| 11 | Execution error | Verify task is approved, check agent config |
| 13 | Comment doesn't send to draft | Verify task was in needs_approval before commenting |
| 17 | Daemon hangs | Check concurrent_tasks config, verify cellos_acp works |
