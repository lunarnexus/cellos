# CelloS Data Model

## Enums (all use `StrEnum`)

### AgentRole
| Value | Inferred TaskType | Description |
|-------|------------------|-------------|
| `researcher` | research | Investigation, information gathering |
| `architect` | architecture | Design planning, technical decisions |
| `engineer` | implementation | Code writing, feature building |
| `tester` | verification | Testing, validation, quality assurance |

### TaskStatus (state machine)
```
draft ──────▶ needs_approval ──────▶ approved ───┬──▶ in_progress ──▶ done
  │                    ▲                      │   │                       │
  │                    │                      │   └───────────────────────┘
  │              [plan]                  execute        (completion)
  │          (any role)              (ACP agent)
  └────────────────────┴────────────────▼
                           approve ←──────┘
                            (human gate)

Comment on needs_approval task: needs_approval ──▶ draft ──▶ [re-plan] ──▶ needs_approval
```

| Value | Description | Transitions To |
|-------|-------------|----------------|
| `draft` | Newly created task | needs_approval (via planning — any role) |
| `needs_approval` | Plan generated, awaiting human review | approved (via approve), draft (via comment to revise) |
| `approved` | Human approved the plan | in_progress (via scheduler picking it up) |
| `in_progress` | Worker executing task | done, failed |
| `done` | Task completed successfully | — (terminal) |
| `blocked` | Dependencies not satisfied or child requested blocking | in_progress (when unblocked), cancelled |
| `failed` | Execution failed | draft (for retry via update) |
| `change_requested` | Child task requested changes to parent plan | needs_approval, approved (if auto-accepted) |
| `cancelled` | Task explicitly cancelled by human | — (terminal) |

### TaskType
| Value | Description |
|-------|-------------|
| `proposal` | Initial proposal or suggestion |
| `research` | Investigation with findings as output |
| `architecture` | Design document, technical decisions |
| `implementation` | Code changes, feature development |
| `verification` | Testing, validation, quality checks |

### AttentionReason (why human should look at this task)
| Value | Triggered When |
|-------|---------------|
| `new_task` | Task created (configurable) |
| `human_changed_task` | Human edited title/details/criteria via update |
| `dependency_done` | A dependency completed, potentially unblocking this task |
| `child_change_requested` | Child execution requested changes to parent plan |
| `child_failed` | A child task failed execution |
| `approved` | Task approved and ready for human awareness before execution |
| `execution_failed` | Worker failed, needs human review |
| `human_commented` | Human added comment on draft/needs_approval task |
| `planning_complete` | Plan generated successfully awaiting approval |

### WorkerStatus
| Value | Description |
|-------|-------------|
| `pending` | Scheduled but not yet started |
| `running` | Subprocess executing |
| `completed` | Finished (success or failure) |
| `failed` | Process crashed or timed out |

### TaskAttemptStatus
| Value | Description |
|-------|-------------|
| `started` | Attempt initiated |
| `succeeded` | Agent returned successful result |
| `failed` | Agent failed, timeout, or error |

### CommentAuthorType
| Value | Description |
|-------|-------------|
| `human` | User via CLI comment command |
| `system` | Auto-generated (e.g., dependency results) |

## Pydantic Models

### Task (central entity — ~25 fields)

```python
class Task(BaseModel):
    id: str                                    # hex UUID[:12]
    title: str                                 # Human-readable task name
    details: Optional[str] = None              # Detailed description/instructions for agent
    status: TaskStatus = TaskStatus.DRAFT      # Current lifecycle state
    role: AgentRole = AgentRole.ENGINEER       # Which agent type handles this
    task_type: TaskType                        # Inferred from role if not explicit; defaults to implementation
    plan: Optional[str] = None                 # Generated plan text (after planning)
    prompt_text: Optional[str] = None          # Additional prompt instructions
    
    parent_id: Optional[str] = None            # Parent task ID (hierarchical)
    dependencies: list[TaskDependency]         # Tasks this depends on
    agent_id: Optional[str] = None             # Specific agent from catalog
    
    success_criteria: Optional[str] = None     # What "done" looks like
    failure_criteria: Optional[str] = None     # Conditions that constitute failure
    
    attention: AttentionMetadata               # Attention tracking state
    processing: ProcessingMetadata             # Sync/change detection metadata
    conversation: list[ConversationMessage]   # Human/agent message history
    result: Optional[TaskResult] = None        # Final execution result
    comments: list[TaskComment]                # Human/system comments
    
    created_at: datetime                       # Creation timestamp
    updated_at: datetime                       # Last modification timestamp

    # Methods
    def requires_attention(self, reason: AttentionReason) -> 'Task': ...  # Returns copy with attention set
    def clear_attention(self) -> 'Task': ...                    # Returns copy with attention cleared
    
    # Backward-compat migration via model_validator(mode="before"):
    #   proposal → prompt_text
    #   description → details  
    #   constraints → failure_criteria
```

### AttentionMetadata

```python
class AttentionMetadata(BaseModel):
    required: bool = False                     # Does human need to look at this?
    reason: Optional[AttentionReason] = None   # Why attention is needed
    detail: Optional[str] = None               # Additional context for the alert
    timestamp: Optional[datetime] = None       # When attention was triggered
    
    @classmethod
    def required_attention(cls, reason, detail=None) -> 'AttentionMetadata': ...
```

### ProcessingMetadata (sync/change detection)

```python
class ProcessingMetadata(BaseModel):
    last_processed_at: Optional[datetime] = None  # Last time scheduler processed this task
    last_human_change_at: Optional[datetime] = None  # Last human modification
    last_ai_change_at: Optional[datetime] = None     # Last agent modification
    input_hash: Optional[str] = None                 # Hash of inputs for change detection
```

### TaskDependency

```python
class TaskDependency(BaseModel):
    task_id: str                                 # ID of the dependency target
    status_satisfied: bool = False               # Whether this dependency is met
```

### ConversationMessage

```python
class ConversationMessage(BaseModel):
    author_type: Literal["human", "agent", "system"]  # Who sent it
    content: str                                   # Message text
    timestamp: datetime                            # When sent
```

### TaskComment

```python
class TaskComment(BaseModel):
    id: str                                        # Unique comment ID
    task_id: str                                   # Parent task reference
    author_type: CommentAuthorType                 # human or system
    author_id: Optional[str] = None                # Human name/agent ID for attribution
    content: str                                   # Comment text
    timestamp: datetime                            # When added
```

### TaskResult

```python
class TaskResult(BaseModel):
    success: bool                                  # Did execution succeed?
    summary: str                                   # Brief result description
    output: Optional[str] = None                   # Full agent output (truncated to 5000 chars)
    actions_taken: list[str] = []                  # Actions performed during execution
    files_changed: list[str] = []                  # Files modified during execution
    commands_run: list[str] = []                   # Commands executed during task
    criteria_met: list[str] = []                   # Success criteria that were met
    issues: list[str] = []                         # Issues encountered during execution
    timestamp: datetime                            # When result was recorded
```

### ChangeRequestReport

```python
class ChangeRequestReport(BaseModel):
    reason: str                                    # Why changes are requested
    requested_changes: list[str]                   # List of changes requested
    timestamp: datetime                            # When report was created
```

### TaskAttempt

```python
class TaskAttempt(BaseModel):
    id: str                                        # Unique attempt ID  
    task_id: str                                   # Parent task reference
    status: TaskAttemptStatus = TaskAttemptStatus.STARTED  # started/succeeded/failed
    mode: Optional[str] = None                     # "planning" or "execution"
    agent_id: Optional[str] = None                 # Which agent handled this attempt
    result_summary: Optional[str] = None           # Brief outcome description
    error_message: Optional[str] = None            # Failure reason if failed
    started_at: datetime                           # Attempt start time
    completed_at: Optional[datetime] = None        # When attempt finished
```

### TaskEvent (audit trail)

```python
class TaskEvent(BaseModel):
    id: str                                        # Unique event ID
    task_id: str                                   # Parent task reference  
    event_type: str                                # e.g., "status_changed", "planning_saved"
    message: str                                   # Human-readable description
    timestamp: datetime                            # When event occurred
```

### Worker (subprocess tracking)

```python
class Worker(BaseModel):
    id: str                                        # Unique worker ID
    task_id: str                                   # Task being worked on
    mode: str                                      # "planning" or "execution"
    status: WorkerStatus = WorkerStatus.PENDING   # pending/running/completed/failed
    pid: Optional[int] = None                      # Process ID of subprocess
    log_path: Optional[str] = None                 # Path to worker log file
    started_at: datetime                           # When spawned
    completed_at: Optional[datetime] = None        # When finished
```

## SQLite Schema

### Table: tasks
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    details TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    role TEXT NOT NULL DEFAULT 'engineer',
    task_type TEXT NOT NULL,
    plan TEXT DEFAULT '',
    prompt_text TEXT DEFAULT '',
    parent_id TEXT REFERENCES tasks(id),
    agent_id TEXT DEFAULT '',
    success_criteria TEXT DEFAULT '',
    failure_criteria TEXT DEFAULT '',
    dependencies TEXT DEFAULT '[]',        -- JSON array of TaskDependency objects
    attention TEXT DEFAULT '{"required": false}',  -- JSON AttentionMetadata object
    processing TEXT DEFAULT '{}',          -- JSON ProcessingMetadata object  
    conversation TEXT DEFAULT '[]',        -- JSON array of ConversationMessage objects
    result TEXT DEFAULT '',                -- JSON TaskResult object or null
    comments TEXT DEFAULT '[]',            -- JSON array of TaskComment objects
    created_at TEXT NOT NULL,              -- ISO format timestamp
    updated_at TEXT NOT NULL               -- ISO format timestamp
);

-- Index for attention queries (more robust than LIKE on JSON blobs)
CREATE INDEX IF NOT EXISTS idx_attention_required 
    ON tasks(json_extract(attention, '$.required'));
```

### Table: task_dependencies
Junction table for explicit dependency tracking with FK constraints:
```sql
CREATE TABLE IF NOT EXISTS task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),      -- Task that depends on another
    depends_on_task_id TEXT NOT NULL REFERENCES tasks(id),  -- The dependency target
    status_satisfied BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL
);
```

### Table: task_results (historical results per attempt)
```sql
CREATE TABLE IF NOT EXISTS task_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    success BOOLEAN NOT NULL,
    summary TEXT DEFAULT '',
    output TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
```

### Table: task_events (audit trail)
```sql
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    event_type TEXT NOT NULL,
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
```

### Table: task_comments
```sql
CREATE TABLE IF NOT EXISTS task_comments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    author_type TEXT NOT NULL,      -- 'human' or 'system'
    author_id TEXT DEFAULT '',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

### Table: task_attempts (execution history)
```sql
CREATE TABLE IF NOT EXISTS task_attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    status TEXT NOT NULL DEFAULT 'started',  -- started/succeeded/failed
    mode TEXT DEFAULT '',                     -- planning or execution
    agent_id TEXT DEFAULT '',
    result_summary TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT DEFAULT ''
);
```

## Notes on Data Design Decisions

### JSON Columns vs Normalized Tables
Complex nested data (conversation history, attention metadata, processing metadata) is stored as JSON strings in the tasks table rather than normalized tables. This keeps queries simple and matches how Pydantic models serialize/deserialize. Trade-off: can't efficiently query inside JSON blobs without json_extract().

### Dependencies Stored Twice
Dependencies exist both inline (JSON array in `tasks.dependencies`) AND as rows in `task_dependencies` junction table. The inline copy is for quick reads; the junction table enforces FK constraints and enables efficient "find all tasks depending on X" queries. They're kept in sync via `_replace_dependencies()` helper.

### Attention Query Strategy
Use `json_extract(attention, '$.required') = 1` with a partial index instead of LIKE queries on JSON blobs. This is more robust against formatting changes and leverages SQLite's JSON functions properly.

### Backward Compatibility
Task model has `model_validator(mode="before")` that maps legacy field names to current ones:
- `proposal` → `prompt_text`
- `description` → `details` 
- `constraints` → `failure_criteria`

This allows loading tasks created by older versions without data migration scripts.

### Config Location
Config files live in `~/.cellos/` by default. The CLI accepts `--config-dir <path>` to point to a different config directory. Example files shipped with the repo are copied on first init.
