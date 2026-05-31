## Verified facts

CelloS is currently described as a pre alpha, human governed AI orchestration system that decomposes work into small reviewable tasks, with the human staying in control at meaningful decision points. ([GitHub][1])

The visible docs already support the direction you described: PM tools are supposed to be “user interfaces and sync surfaces,” while CelloS keeps canonical project state locally, and Trello is named as the first PM adapter target. ([GitHub][2])

The staged implementation plan says the PM adapter contract is still future work: define adapter interfaces for sync, discovery, updates, and task creation; store PM sync metadata; isolate adapter failures; and write fake adapter tests before Trello. ([GitHub][3]) It also defines a later Trello MVP: read board, list, and card metadata, filter cards by a case insensitive `cellos` label, map Trello lists to CelloS states, detect human edits, comments, and list moves, and write prompts, results, and comments back to cards. ([GitHub][3])

The current CelloS model already has useful hooks for this: `Task.metadata`, `ProcessingMetadata` fields for external change observation and processing, and an `EXTERNAL_STATE_CHANGED` attention reason. ([GitHub][4]) The database already has `task_events`, which fits the audit trail requirement for external UI activity. ([GitHub][5])

Current runtime config only models `scheduler` and `worker`; there is no verified PM connector config schema in `cellos/config.py` yet. ([GitHub][6])

I could not verify a `project-charter.md` in the visible root file list or docs file list. The repo root shows `cellos`, `docs`, `tests`, README, examples, and config files, but not `project-charter.md`. ([GitHub][7]) The docs folder lists `pm-adapters.md` and `trello.md`, but I could not fetch their contents successfully, so I am treating the visible docs README and implementation plan as the verified planning source. ([GitHub][2])

## Best PM tool options

| Priority | Tool                            | Why it fits CelloS                                                                                                                                                                                                                                        | Main caveat                                                                                                                                                                                 |
| -------: | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
|        1 | **Trello**                      | Best first target. Card equals task, list equals lifecycle state, label equals role or task type, comments equal human input. Trello supports creating, reading, updating cards, adding comments, custom fields, and webhooks. ([Atlassian Developer][8]) | Several Trello card resources say Forge and OAuth2 apps cannot access them, so the MVP should use Trello API key plus token unless you verify a newer auth path. ([Atlassian Developer][8]) |
|        2 | **GitHub Issues plus Projects** | Strong fit for developer work. GitHub Issues API manages issues, comments, labels, milestones, and assignees; GitHub Projects is managed through GraphQL. ([GitHub Docs][9])                                                                              | GitHub Projects adds GraphQL complexity. GitHub Issues alone is simpler but less PM like.                                                                                                   |
|        3 | **Linear**                      | Strong engineering PM UI. Linear’s public API is GraphQL and it supports webhooks for created or updated data. ([Linear][10])                                                                                                                             | GraphQL first connector means more adapter complexity than Trello.                                                                                                                          |
|        4 | **Asana**                       | Good general PM option. Asana supports task creation, task updates, comments through stories, project or section placement, and webhooks. ([Asana Docs][11])                                                                                              | More flexible than Trello, which means mapping sections, custom fields, and projects needs more configuration.                                                                              |
|        5 | **Jira Cloud**                  | Best enterprise option. Jira Cloud exposes issue get, edit, assign, transition, comments, changelogs, and webhooks in its REST API. ([Atlassian Developer][12])                                                                                           | Status transitions are workflow dependent, so it should come after the adapter contract is stable.                                                                                          |
|        6 | **ClickUp**                     | Broad PM suite. ClickUp tasks support descriptions, assignees, priorities, due dates, tags, custom fields, parent tasks, dependencies, task comments, and webhooks. ([ClickUp][13])                                                                       | Its hierarchy and custom fields are powerful but heavier to configure.                                                                                                                      |
|        7 | **Notion**                      | Good read/write planning surface. Notion’s API can read, create, and update pages, databases, users, comments, and more, and it has webhooks. ([Notion Docs][14])                                                                                         | Notion webhooks are signals only; the event does not include full changed content, so the connector must fetch the changed page/database after receiving the webhook. ([Notion Docs][15])   |

## Recommendation

Start with **Trello**, then add **GitHub Issues/Projects**, then **Linear**, then **Asana or Jira** depending on your target users.

Trello is the best MVP because it matches the existing CelloS lifecycle with the least translation. GitHub should be second because CelloS is developer oriented and GitHub is likely where implementation work already lives. Linear is a good third because it is popular with engineering teams, but its GraphQL model is a larger adapter test.

## Core design

The PM tool should never be the authority. It should be an **external interaction surface**.

That means:

```text
PM tool event
→ connector receives event
→ connector normalizes event into a CelloS PM event
→ CelloS validates it against lifecycle rules
→ CelloS writes to SQLite
→ CelloS records task_event
→ outbound sync reconciles the PM card or issue back to canonical CelloS state
```

The important rule is that a Trello card, GitHub issue, or Linear issue is a **mirror plus input device**, not the task record itself.

## Proposed module layout

```text
cellos/
  pm/
    __init__.py
    base.py
    models.py
    registry.py
    mapping.py
    sync.py
    inbound.py
    outbound.py
    errors.py

    adapters/
      __init__.py
      fake.py
      trello.py
      github.py
      linear.py
      asana.py
      jira.py
      clickup.py
      notion.py
```

`cellos/pm/base.py` should define the stable connector protocol.

```python
class PmAdapter(Protocol):
    name: str

    async def discover(self) -> PmDiscoveryResult:
        ...

    async def pull_events(self, since: datetime | None) -> list[PmEvent]:
        ...

    async def get_external_task(self, external_id: str) -> PmExternalTask:
        ...

    async def create_external_task(self, task: Task) -> PmExternalTask:
        ...

    async def update_external_task(self, task: Task, binding: PmBinding) -> PmExternalTask:
        ...

    async def append_external_comment(
        self,
        binding: PmBinding,
        body: str,
        visibility: str = "public",
    ) -> PmExternalComment:
        ...
```

Use `fake.py` first, because the implementation plan explicitly calls for fake adapter tests before Trello. ([GitHub][3])

## Data model additions

Do not cram this entirely into `Task.metadata`. Use `Task.metadata` for adapter specific annotations, but add real tables for sync state.

```sql
CREATE TABLE pm_connections (
  id TEXT PRIMARY KEY,
  adapter TEXT NOT NULL,
  name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE pm_bindings (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  external_type TEXT NOT NULL,
  external_id TEXT NOT NULL,
  external_url TEXT,
  external_parent_id TEXT,
  last_external_updated_at TEXT,
  last_external_hash TEXT,
  last_cellos_updated_at TEXT,
  sync_status TEXT NOT NULL DEFAULT 'ok',
  payload_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(connection_id, external_type, external_id),
  FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
  FOREIGN KEY(connection_id) REFERENCES pm_connections(id) ON DELETE CASCADE
);

CREATE TABLE pm_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  connection_id TEXT NOT NULL,
  external_event_id TEXT,
  external_type TEXT NOT NULL,
  external_id TEXT,
  task_id TEXT,
  event_type TEXT NOT NULL,
  received_at TEXT NOT NULL,
  processed_at TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  payload_json TEXT NOT NULL,
  error TEXT,
  UNIQUE(connection_id, external_event_id),
  FOREIGN KEY(connection_id) REFERENCES pm_connections(id) ON DELETE CASCADE
);
```

This gives you idempotency, replay, auditability, and clean connector isolation.

## Canonical mapping

### CelloS task to generic PM task

```text
Task.id                 → external custom field or hidden marker
Task.title              → card/issue/task title
Task.description        → card/issue/task body
Task.prompt             → "Current approved plan" section or pinned/sync comment
Task.status             → list, section, status field, or project status
Task.role               → label, custom field, or assignee rule
Task.task_type          → label or custom field
Task.parent_id          → parent issue, linked task, checklist, or relation
Task.dependencies       → blocked by / linked issue / dependency relation
Task.attention.required → label like "cellos:attention" or status field
Task.result             → comment or "Result" section
task_events             → external comments only for human useful events
```

### Trello MVP mapping

```text
Board                   → CelloS project workspace
List                    → CelloS status
Card                    → CelloS task
Card label "cellos"     → managed by CelloS
Card custom field       → cellos_task_id
Card comments           → human comments or CelloS status/result updates
Card movement           → requested status change
Card description        → rendered CelloS task summary
Checklist               → optional child tasks or dependencies later
```

Trello card creation and updates are officially supported through `POST /cards` and `PUT /cards/{id}`. ([Atlassian Developer][8]) Trello comments are supported through `POST /cards/{id}/actions/comments`. ([Atlassian Developer][8]) Trello custom fields can store the CelloS task ID through the custom field item endpoint. ([Atlassian Developer][8]) Trello webhooks can subscribe to a model through `callbackURL` and `idModel`. ([Atlassian Developer][16])

## Inbound behavior rules

External PM actions should become **intent**, not blind writes.

| External action                             | CelloS behavior                                                                                                        |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| User adds comment                           | Add task event, mark attention as human commented, optionally append to task conversation later.                       |
| User edits title or description             | Apply through CelloS update service, record task event, mark attention unless the task is still draft.                 |
| User moves Trello card to `approved`        | Run the same approval validation as `cellos approve`; reject or revert if lifecycle rules do not allow it.             |
| User moves card to `done`                   | Treat as a completion claim only if the task was externally completed by a human. Otherwise mark attention for review. |
| User creates a new card with `cellos` label | Create a draft CelloS task if adapter policy allows external task creation.                                            |
| User deletes or archives external card      | Do not delete CelloS task. Mark binding as external missing and add attention.                                         |

## Outbound behavior rules

CelloS should always reconcile external UI back to the database state.

Outbound sync should:

1. Create missing external cards/issues for tasks that match connector policy.
2. Update title, description, status/list, labels, and custom fields from CelloS.
3. Append comments for planning complete, approval needed, result saved, blocked, failed, and attention events.
4. Never overwrite a user comment.
5. Never delete external objects automatically in MVP. Archive or label as stale later.

## Config shape

Current config needs to be extended because the verified config schema only has scheduler and worker settings. ([GitHub][6])

Proposed config:

```json
{
  "scheduler": {
    "concurrent_tasks": 4,
    "worker_timeout_seconds": 300
  },
  "worker": {
    "backend": "acp",
    "command": ["opencode"],
    "debug_log_path": ".cellos/logs/worker-debug.log"
  },
  "pm": {
    "enabled": true,
    "sync_on_run": true,
    "connections": [
      {
        "id": "trello-main",
        "adapter": "trello",
        "enabled": true,
        "board_id": "TRELLO_BOARD_ID",
        "managed_label": "cellos",
        "status_lists": {
          "draft": "LIST_ID_DRAFT",
          "needs_approval": "LIST_ID_NEEDS_APPROVAL",
          "approved": "LIST_ID_APPROVED",
          "in_progress": "LIST_ID_IN_PROGRESS",
          "done": "LIST_ID_DONE",
          "failed": "LIST_ID_FAILED",
          "blocked": "LIST_ID_BLOCKED",
          "change_requested": "LIST_ID_CHANGE_REQUESTED",
          "cancelled": "LIST_ID_CANCELLED"
        },
        "allow_external_task_creation": true,
        "allow_external_approval": true,
        "allow_external_done": false
      }
    ]
  }
}
```

Secrets should not live in this file. Use environment variables such as:

```text
CELLOS_TRELLO_KEY
CELLOS_TRELLO_TOKEN
CELLOS_GITHUB_TOKEN
CELLOS_LINEAR_API_KEY
CELLOS_ASANA_TOKEN
CELLOS_JIRA_EMAIL
CELLOS_JIRA_API_TOKEN
```

## Build plan

### Phase 1: PM neutral foundation

Add `cellos/pm/models.py`, `cellos/pm/base.py`, `cellos/pm/sync.py`, and `cellos/pm/adapters/fake.py`.

Acceptance checks:

```bash
python -m pytest tests/test_pm_fake_adapter.py -q
```

Expected result:

```text
all fake adapter tests pass
pm_events are idempotent
pm_bindings are created once per external object
task_events are written for inbound PM events
```

### Phase 2: DB migration

Add a migration path for `pm_connections`, `pm_bindings`, and `pm_events`.

Acceptance checks:

```bash
cellos init --hard-reset
sqlite3 .cellos/cellos.sqlite ".tables"
```

Expected tables:

```text
pm_connections
pm_bindings
pm_events
tasks
task_dependencies
task_results
task_events
```

### Phase 3: Sync engine

Implement:

```text
sync_inbound(connection_id)
sync_outbound(connection_id)
sync_once()
```

Hook `sync_once()` into `cellos run` when `pm.sync_on_run` is true. The CLI remains development/debug only, but `cellos run` becomes the operational heartbeat for PM reconciliation.

### Phase 4: Trello MVP

Implement only:

```text
discover board lists
find cards with managed label
create card for CelloS task
update card title/description/list/labels/custom field
append card comment
receive or poll board/card changes
translate comments and list moves into CelloS events
```

Do not implement checklist child task creation until approval rules for AI task creation are enforced, because the implementation plan explicitly calls out approval before filesystem or PM writes and approved scope before child card creation. ([GitHub][3])

### Phase 5: GitHub connector

Start with GitHub Issues only, then add Projects v2 fields.

```text
Issue title/body       → Task title/description
Labels                 → role, type, status, attention
Issue comments         → human comments and CelloS status updates
Project status field   → lifecycle state
```

Use GitHub Issues REST for issues/comments/labels and GitHub Projects GraphQL only for board status. ([GitHub Docs][9])

### Phase 6: Linear, Asana, Jira

Add these only after Trello and GitHub prove the adapter contract.

Linear should be a GraphQL adapter. Asana should be a task/section/story adapter. Jira should be an issue/workflow transition adapter.

## Important implementation guardrails

Do not let adapters import worker or agent code. PM adapters should only translate external PM data into CelloS domain events.

Do not let adapters update task rows directly. They should call a CelloS service layer such as:

```python
await task_service.apply_external_comment(...)
await task_service.request_status_change(...)
await task_service.create_external_draft_task(...)
await task_service.record_external_missing(...)
```

Do not delete CelloS tasks because an external card was deleted. The database is authoritative.

Do not store API tokens in SQLite task metadata. Store only connection IDs, external IDs, URLs, hashes, and timestamps.

## Unknown / cannot verify

I cannot verify the contents of `project-charter.md` from the public repo view. I also cannot verify the contents of `docs/pm-adapters.md` or `docs/trello.md`; the docs index lists them, but the file fetches failed from the public URL. The plan above is based on the verified README, docs index, implementation plan, visible code, and official PM API documentation.

[1]: https://raw.githubusercontent.com/lunarnexus/cellos/main/README.md " [-d details] [-r role] [-t type] [-s success] [-f failure] [--depends ids]` | Create task |
\| `status [-s status_filter] [--all]` | List tasks with ⚠️ attention markers |
\| `detail <task_id>` | Full task info (plan, conversation, comments) |
\| `approve <task_id>` | Approve NEEDS_APPROVAL task (human gate) |
\| `comment <task_id> -m message` | Add human comment + trigger attention |
\| `events <task_id> [--limit N]` | Show audit trail |
\| `update <task_id> [--title] [--status] [--add-dep] [--remove-dep]` | Update any field |
\| `plan <task_id>` | Generate plan via agent (any role, task must be draft) |
\| `execute <task_id>` | Execute approved task via agent (manual trigger) |
\| `worker <task_id> --mode planning\\|execution` | Run single worker (called by spawner) |
\| `run` | Start event-driven daemon scheduler |

\## Configuration

Three JSON files in `~/.cellos/`:

\**config.json** — Scheduler, worker, and agent settings:
\```json
{
  \"scheduler\": { \"concurrent_tasks\": 4, \"heartbeat_interval_seconds\": 5.0 },
  \"worker\": { \"backend\": \"acp\", \"timeout_seconds\": 300 },
  \"agents\": { \"default_agent_id\": \"engineer\" }
}
\```

\**agentcatalog.json** — Agent definitions:
\```json
{
  \"engineer\": { \"connector\": \"cellos_acp\", \"options\": { \"agent\": \"opencode\", \"auto_approve\": true } }
}
\```

\**promptprofiles.json** — Role instructions and mode-specific prompt sections.

\## Task Lifecycle

\```
draft ──▶ needs_approval ──▶ approved ──▶ done
  │              ▲               │          │
  │         [plan]             execute    failed
  │              │              (agent)     │
  └────── [approve] ←──────────┘            │
           (human gate)                      │
                                            cancelled
\```

Attention signals trigger on: human changes, comments, planning complete, dependency done.

\## Architecture

\- **Event-driven daemon** (asyncio.Event wake, lightweight file watcher fallback)
\- **Protocol-based ACP connectors** for agent communication
\- **Repository pattern** persistence with SQLite
\- **Rich CLI output** with attention tracking
\- **Subprocess worker isolation** (hung workers don't kill scheduler)

See `docs/` for detailed architecture, data model, and build plans.

\## Testing

\```bash
python -m pytest tests/ -v      # Full test suite
python -m pytest tests/ -q      # Quiet mode
\```

See `docs/smoke-test.md` for the 15-step sequential validation flow.

\## Troubleshooting

\| Issue | Fix |
\|-------|-----|
\| Config not found | Run `cellos init` |
\| Cannot approve draft task | Task must be in `needs_approval` status |
\| Worker error with cellos_acp | Check agent binary is available; use `fake_acp` connector in config for testing |
\| Daemon exits quickly | Exits after 60 idle cycles (~5 min); ensure tasks exist |
"
[2]: https://github.com/lunarnexus/cellos/tree/main/docs "cellos/docs at main · lunarnexus/cellos · GitHub"
[3]: https://raw.githubusercontent.com/lunarnexus/cellos/main/docs/implementation-plan.md "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/lunarnexus/cellos/main/cellos/models.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/lunarnexus/cellos/main/cellos/db.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/lunarnexus/cellos/main/cellos/config.py "raw.githubusercontent.com"
[7]: https://github.com/lunarnexus/cellos/ "GitHub - lunarnexus/cellos: Hierarchical AI orchestration framework · GitHub"
[8]: https://developer.atlassian.com/cloud/trello/rest/api-group-cards/ "The Trello REST API"
[9]: https://docs.github.com/rest/issues "REST API endpoints for issues - GitHub Docs"
[10]: https://linear.app/docs/api-and-webhooks "API and Webhooks – Linear Docs"
[11]: https://developers.asana.com/reference/createtask?utm_source=chatgpt.com "Create a task"
[12]: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/ "The Jira Cloud platform REST API"
[13]: https://developer.clickup.com/docs/tasks "Tasks"
[14]: https://developers.notion.com/guides/get-started/overview "Overview - Notion Docs"
[15]: https://developers.notion.com/reference/webhooks-events-delivery "Event types & delivery - Notion Docs"
[16]: https://developer.atlassian.com/cloud/trello/rest/api-group-webhooks/ "The Trello REST API"

