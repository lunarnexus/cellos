# Suggestions

I've analyzed the Hermes Agent Kanban skills and compared against CelloS.

1.

Kanban stores each dispatch attempt as a separate row in `task_runs` with:
- outcome (completed/blocked/crashed/timed_out/spawn_failed/reclaimed)
- summary, metadata, error, PID, timestamps

CelloS has a single `task_results` row per task — if a task fails and is retried, the previous attempt's data is overwritten.

Consider tracking each attempt separately so retry history, errors, and PIDs are preserved rather than lost.

    Why it matters for CelloS: retry diagnostics. When a worker crashes, OOMs, or times out, the next attempt needs to know what went wrong. Currently CelloS just overwrites the result. Kanban's approach lets workers read prior attempts and avoid repeating the same failure.

    2. Claim locks with TTL + crash detection
    
    Kanban uses atomic CAS (compare-and-swap) on claim_lock + claim_expires to prevent two workers from claiming the same task. The dispatcher also checks worker_pid against the OS to detect crashed workers before the TTL expires. CelloS just marks tasks as in_progress with no lock or crash detection.
    
    Why it matters: if CelloS spawns a worker that segfaults or gets OOM-killed, the task sits in in_progress forever. Kanban's dispatcher reclaims it on the next tick.
  
    5. Auto-blocking after spawn failures
    
    Kanban counts spawn_failures per task. After N consecutive failures, it auto-blocks the task with the last error as the reason. CelloS has no failure counting -- a broken worker command would thrash forever.
    
    Why it matters: prevents infinite spawn loops when a profile config is broken, a credential is missing, or a command path is wrong.
    

    7. Task comments (separate from events)
    
    Kanban has a task_comments table with author/body/timestamp. CelloS has task_events which is more of an audit log. Comments are for human-AI collaboration -- leaving context, asking questions, providing feedback.
    
    Why it matters: when a reviewer blocks a task with "needs changes," the feedback lives in the comment thread, not buried in event payloads.
    
    8. Workspace kinds (scratch/worktree/dir)
    
    Kanban tasks declare a workspace kind: scratch (fresh tmp dir), worktree (git worktree), or dir:<path> (shared persistent directory). CelloS workers just run in the workdir with no isolation.
    
    Why it matters: research tasks get clean scratch spaces. Coding tasks get git worktrees. Shared tasks get persistent directories. Prevents cross-task file contamination.
    
    Medium-impact concepts

    9. Task priority ordering -- Kanban orders ready tasks by priority DESC, created_at ASC. CelloS just uses created_at.
    
    10. Task archiving + garbage collection -- Kanban has archived status and a gc command to clean up old workspaces/logs. CelloS has no archival.
    
    11. Idempotency keys -- Kanban supports idempotency_key to prevent duplicate task creation. Useful for automated task generators.
    

    14. Notification subscriptions -- Kanban has kanban_notify_subs for pushing completed/blocked events back to gateway users. CelloS has no notification system.
    
  
