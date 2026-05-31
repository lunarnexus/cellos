# CelloS Smoke Test

Sequential validation flow covering the complete CelloS system.
Each step must pass before proceeding to the next.

**Process:**
The user wants you to step through each step one-by-one.  Before each step, list the step and commands, what the step proves, what we should expect to see.  
If there's a failure, stop the test and explain, don't attempt to fix anything.



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

**Expected:** Shows command group with all subcommands listed: init, add-task, status, detail, approve, comment, events, update, plan, execute, worker, run, attempts.

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

## Step 4: Create and Plan Task

Create a task and generate a plan via agent.

```bash
TASK_ID=$(cellos add-task "Count lines and report your findings" -d "Count the number of lines in ~/workspace/cellos/README.md and report back" -r architect | grep -oP 'Created task \K[^:\s]+')
cellos status
cellos --debug plan $TASK_ID
```

**Expected:** Task created with ID, role=architect, status=draft. After planning: "Plan generated for <id>", status=needs_approval with ⚠️ attention marker. Architect plans describe child task(s) that will be created after approval; no child tasks are created during planning.

**Debug verification:** With `--debug`, `~/.cellos/debug.log` should include the exact prompt sent from Cellos to cellos-acp and the raw response returned from cellos-acp before Cellos parses or saves it. Look for `cellos-acp request body`, `cellos-acp response metadata`, `cellos-acp response combined body`, and `Planning result raw input`. The default `text_wait` for late ACP text chunks is `2.0` seconds. The default agent catalog also enables cellos-acp library debug logging at `~/.cellos/cellos-acp.log` via the `log_file` option.

---

## Step 5: Inspect Task State

Verify task detail, events, and approval.

```bash
cellos detail $TASK_ID
cellos events $TASK_ID
cellos approve $TASK_ID
cellos detail $TASK_ID
```

**Expected:**
- Detail: Panel showing title, status=needs_approval, role, type, details, plan text with planned child task(s), and ⚠️ attention marker.
- Events: Chronological events including task_created, planning_saved, status_changed.
- Approve: "✓ Approved task <id>", status=approved.
- Detail after approve: Status=approved. Child tasks are not created until the approved parent task executes.

---

## Step 6: Child Tasks via Daemon

Verify the full child-task lifecycle: daemon executes approved parent to create children, daemon plans children, human approves children, daemon executes children, parent auto-completes.

```bash
# Start daemon in background. It will execute the approved architect parent,
# create child tasks, plan draft children, and execute approved children.
cellos --debug run > /tmp/cellos_daemon.log 2>&1 &
DAEMON_PID=$!
cleanup_daemon() {
    kill $DAEMON_PID 2>/dev/null
    wait $DAEMON_PID 2>/dev/null
}
trap cleanup_daemon EXIT

# Wait for parent execution to create child tasks.
CHILD_IDS=""
for i in {1..150}; do
    CHILD_IDS=$(cellos detail $TASK_ID | grep 'Children:' | grep -oP '[0-9a-f]{12}' | sort -u)
    if [ -n "$CHILD_IDS" ]; then
        break
    fi
    sleep 2
done
if [ -z "$CHILD_IDS" ]; then
    echo "Timed out waiting for child tasks"
    exit 1
fi

# Wait for daemon to plan children (draft → needs_approval).
for CHILD in $CHILD_IDS; do
    for i in {1..150}; do
        if cellos detail $CHILD | grep -q 'Status:       needs_approval'; then
            break
        fi
        sleep 2
    done
    cellos detail $CHILD | grep -q 'Status:       needs_approval' || {
        echo "Timed out waiting for child $CHILD to need approval"
        exit 1
    }
done
cellos status -s needs_approval

# Approve all planned children.
for CHILD in $CHILD_IDS; do
    cellos approve $CHILD
done

# Wait for daemon to execute approved children.
for CHILD in $CHILD_IDS; do
    for i in {1..150}; do
        if cellos detail $CHILD | grep -q 'Status:       done'; then
            break
        fi
        sleep 2
    done
    cellos detail $CHILD | grep -q 'Status:       done' || {
        echo "Timed out waiting for child $CHILD to finish"
        exit 1
    }
done

# Verify parent auto-completed when all children finished.
for i in {1..60}; do
    if cellos detail $TASK_ID | grep -q 'Status:       done'; then
        break
    fi
    sleep 2
done
cellos detail $TASK_ID | grep -q 'Status:       done' || {
    echo "Timed out waiting for parent $TASK_ID to finish"
    exit 1
}

# Stop daemon
cleanup_daemon
trap - EXIT

# Show final parent and child state.
cellos detail $TASK_ID
for CHILD in $CHILD_IDS; do
    cellos detail $CHILD
done
```

**Expected:** Approved parent executes and creates child tasks. Children are planned (needs_approval), approved, executed by daemon (done). Parent task status: done (all child tasks completed). Parent detail lists Children; child detail lists Parent. The daemon is not stopped until these states are observed or a timeout occurs. If any child failed, parent shows ⚠️ attention with reason child_failed.

---

## Step 7: Engineer Lifecycle

Test the full engineer task lifecycle: plan, approve, execute.

```bash
ENG_ID=$(cellos add-task "Count lines in README.md" -d "Use wc -l to count lines in ~/workspace/cellos/README.md and report the count" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos --debug plan $ENG_ID
cellos approve $ENG_ID
cellos --debug execute $ENG_ID
cellos detail $ENG_ID
```

**Expected:** Task planned (needs_approval), approved, executed, status: done with result summary.

---

## Step 8: Comment Revision Flow

Commenting on a `needs_approval` task sends it back to `draft` for re-planning.

```bash
REV_ID=$(cellos add-task "Plan a login form" -d "Plan a hypothetical login form with email and password fields. Do not inspect project files; produce a generic implementation plan only." -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos --debug plan $REV_ID
cellos comment $REV_ID -m "Also add a 'Remember me' checkbox"
cellos detail $REV_ID  # Should show draft status
cellos --debug plan $REV_ID
cellos detail $REV_ID  # Should show needs_approval again, plan includes checkbox
```

**Expected:** After comment, task transitions to `draft`. Re-planning considers the comment and generates an updated plan.

---

## Step 9: Guard Tests

Verify error guards for invalid operations.

```bash
# Invalid approval (draft task)
DRAFT_ID=$(cellos add-task "Draft task" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos approve $DRAFT_ID

# Empty update
cellos update $DRAFT_ID
```

**Expected:**
- "Error: Cannot approve task in status 'draft'. Must be 'needs_approval'."
- "Error: No fields provided to update for task <id>"

---

## Step 10: Dependencies

Create tasks with dependencies.

```bash
PARENT_ID=$(cellos add-task "Parent task" -r engineer | grep -oP 'Created task \K[^:\s]+')
CHILD_ID=$(cellos add-task "Child task" -r engineer | grep -oP 'Created task \K[^:\s]+')
cellos update $PARENT_ID --add-dep $CHILD_ID
cellos detail $PARENT_ID
```

**Expected:** Parent task shows dependency on child in detail view.

---

## Troubleshooting

| Step | Symptom | Fix |
|------|---------|-----|
| 1 | Import errors | `pip install -e ".[dev]"` |
| 3 | Config not found | Delete `~/.cellos` and re-run `cellos init` |
| 4 | Planning error | Check cellos_acp config in agentcatalog.json |
| 4 | Plan appears truncated | Compare `cellos-acp response combined body` with `Planning result raw input` in `~/.cellos/debug.log` |
| 4 | Need lower-level ACP diagnostics | Check `~/.cellos/cellos-acp.log` |
| 6 | Children not planned | Check daemon output, verify children are in draft status |
| 6 | Children not executed | Verify children were approved, check daemon picked them up |
| 7 | Execution error | Verify task is approved, check agent config |
| 8 | Comment doesn't send to draft | Verify task was in needs_approval before commenting |
