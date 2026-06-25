# PM Tools Research for CelloS Integrations

Comprehensive research on open-source project management tools suitable as sync targets for CelloS task connectors. Research compiled June 2026.

## Table of Contents

1. [Overview](#overview)
2. [Tool Deep Dives](#tool-deep-dives)
   - [WeKan](#wekan)
   - [Plane](#plane)
   - [OpenProject](#openproject)
   - [Taiga](#taiga)
   - [Vikunja](#vikunja)
   - [Leantime](#leantime)
   - [Planka](#planka)
   - [Kanboard](#kanboard)
3. [Comparison Matrix](#comparison-matrix)
4. [API Quirks Summary](#api-quirks-summary)
5. [Concept Mapping Guide](#concept-mapping-guide)
6. [Recommendations for CelloS](#recommendations-for-cellos)

---

## Overview

### Selection Criteria

Tools evaluated based on:

- **REST API quality** — Standard CRUD endpoints with proper HTTP methods
- **Authentication model** — API tokens vs. session auth, token expiration
- **Webhooks** — Ability to be notified of changes (push sync) vs. polling
- **Data model alignment** — How closely the tool's concepts match CelloS tasks
- **License** — OSI-approved open source vs. fair-code/source-available
- **Maintenance** — Active development, recent releases, community health
- **Ecosystem** — SDKs, n8n nodes, MCP support

### Final Ranked List

| Rank | Tool | License | Stars | Best For |
|------|------|---------|-------|----------|
| 1 | **Vikunja** | AGPLv3 | ~4.5k | Simplest integration — clean REST API, webhooks, task-centric model |
| 2 | **WeKan** | MIT | ~21k | Near 1:1 Trello API mapping — minimal translation needed |
| 3 | **Plane** | AGPLv3 | ~51k | Modern developer PM — best Jira/Linear replacement |
| 4 | **Planka** | Fair-use | ~12k+ | Direct Trello equivalent — WebSocket push sync |
| 5 | **OpenProject** | GPL v3 | ~13k | Enterprise PM — Gantt, governance, reporting |
| 6 | **Taiga** | AGPLv3 | ~834 | Agile/Scrum teams — built-in workflow support |
| 7 | **Leantime** | AGPLv3 | ~9.4k | Non-technical teams — strategy/OKR focus |
| 8 | **Kanboard** | MIT | ~9.6k | Lightweight Kanban — in maintenance mode |

---

## Tool Deep Dives

### WeKan

**GitHub:** `wekan/wekan`
**Description:** Open-source Trello-like Kanban board built with Meteor.js
**Website:** https://wekan.fi

#### Stats

- **GitHub Stars:** ~21,000
- **License:** MIT
- **Latest Release:** v9.35 (Jun 6, 2026)
- **Total Releases:** ~660
- **Languages:** JavaScript (Meteor), CoffeeScript
- **Deployment:** Docker-first, snap, native binaries

#### API Overview

- **Base URL:** `http(s)://<host>/api/vX.Y/` (version embedded in path)
- **Spec Download:** `wekan.fi/api/v9.57/` (OpenAPI/Swagger spec available)
- **Authentication:** Session-based login — `POST /users/login` returns `{id, token, tokenExpires}`
- **Auth Header:** `Authorization: Bearer <token>`
- **Rate Limiting:** Not documented
- **Pagination:** Via query params `limit`, `skip`

**Endpoints covered:**
- `/boards/` — CRUD for boards
- `/lists/` — CRUD for lists (columns)
- `/cards/` — CRUD for cards
- `/attachments/` — Card attachments
- `/labels/` — Board labels
- `/users/` — Authentication, user management
- `/import-trello/` — Built-in Trello JSON import

#### API Quirks

| Quirk | Detail | CelloS Impact |
|-------|--------|---------------|
| Plaintext password on login | `POST /users/login` sends `{username, password}` over HTTPS | Must use SSL. Token valid until `tokenExpires` |
| Inconsistent content types | Some endpoints accept JSON, others form-urlencoded | JSON format confirmed working; form-urlencoded has known bugs (#4807) |
| No API key generation | Must use existing user credentials | No dedicated integration user model |
| Trello import bug | Issue #5693: cards not imported from Trello JSON | Not directly relevant to CelloS |
| Auth token expiration | Tokens have an `expiresAt` timestamp | Must implement token refresh logic |
| Version in URL path | API version embedded in URL (`/api/v9.57/`) | Must track API version per deployed instance |
| No webhook native support | No built-in webhook system | CelloS must use polling for pull sync |

#### Data Model

```
Board (boards)
├── Lists (lists) — card containers
│   └── Cards (cards) — the actual tasks
│       ├── Labels (labels)
│       ├── Attachments (attachments)
│       ├── Comments
│       ├── Checklists
│       └── Due dates
```

**Mapping to CelloS:** Direct 1:1. Boards → Workspace, Lists → Board/List, Cards → Tasks. Minimal translation needed.

#### Deployment Complexity

- Docker compose: Simple (Wekan + MongoDB)
- No external dependencies beyond database
- Single binary deployment option available
- Configuration via environment variables

#### Ecosystem

- Helm charts: `wekan/charts` (5 stars)
- Python client: `python-wekan` on PyPI
- Large community, 3+ years of API development

---

### Plane

**GitHub:** `makeplane/plane`
**Description:** Open-source project management — Jira, Asana, Linear alternative
**Website:** https://plane.so

#### Stats

- **GitHub Stars:** ~51,000
- **License:** AGPLv3
- **Latest Release:** Active (v1.x, frequent releases)
- **Languages:** Python (Django backend), React (frontend)
- **Deployment:** Docker compose, Kubernetes

#### API Overview

- **Base URL:** `/api/v1/` (public) + `/api/v1.1/`
- **Spec:** `developers.plane.so/api-reference/introduction` (full REST docs)
- **Authentication:** API key (`X-API-Key: <key>`) + OAuth 2.0 for apps
- **Auth Header:** `X-API-Key` or `Authorization: Bearer <token>` for OAuth apps

**Endpoints covered (extensive):**
- `/api/v1/projects/` — Project management
- `/api/v1/issues/` — Work item CRUD (full-featured)
- `/api/v1/cycles/` — Sprint/iteration management
- `/api/v1/modules/` — Milestone/phase management
- `/api/v1/views/` — Custom views
- `/api/v1/issue-types/` — Work item type customization
- `/api/v1/workspace/` — Workspace management
- `/api/v1/integrations/` — Third-party integrations

**Unique features:**
- Rate limiting: 60 requests/minute per API key
- Cursor-based pagination: `value:offset:is_prev` format (e.g., `20:1:0`)
- Webhooks per workspace
- OAuth 2.0 app registration
- Python SDK: `plane-sdk` on PyPI
- PHP SDK: `plane-py` (community)

#### Webhooks

- **Configured per workspace** — Admin panel UI or API
- **Event types:** Issue created, updated, deleted; cycle events, etc.
- **Known bugs:**
  - Duplicate POSTs on state changes (Issue #6848)
  - Events not triggered for API-created issues (Issue #6746)
  - Double payload on certain transitions (Issue #7249)
- **Impact:** Polling may be more reliable than webhooks for CelloS pull sync

#### API Quirks

| Quirk | Detail | CelloS Impact |
|-------|--------|---------------|
| Webhook reliability | Duplicate POSTs (#6848), API events not triggering (#6746) | Polling safer for bidirectional sync; webhooks for notification only |
| Rate limiting | 60 req/min per API key | Implement backoff on 429; cache to minimize reads |
| Unusual pagination | Cursor format `value:offset:is_prev` | Must parse custom cursor (not standard) |
| Pages API missing on self-hosted | Issue #8986 — not reachable via public REST API | Not relevant for CelloS (uses Issues, not Pages) |
| Some endpoints missing | Integrations not exposed (#8906), member management limited (#8459) | Core CRUD for issues/projects/cycles is complete |
| OAuth 2.0 less tested | API key auth fully documented; OAuth less battle-tested | Use API keys for CelloS integration |

#### Data Model

```
Workspace
├── Projects (projects)
│   ├── Cycles (cycles) — time-boxed iterations (sprints)
│   │   └── Issues — work items within a cycle
│   ├── Modules (modules) — milestones/phases
│   │   └── Issues — work items within a module
│   ├── Views (views) — saved filters
│   └── Issues (issues) — work items (can be unassociated)
│       ├── Sub-issue links
│       ├── Labels
│       ├── State (status)
│       ├── Priority
│       ├── Estimate points
│       ├── Attachments
│       └── Comments
```

**Mapping to CelloS:** Multi-layered. Projects → Workspace, Issues → Tasks. Cycles/modules are overhead. State fields map to status. Labels map to tags.

#### Deployment Complexity

- Docker compose: Moderate complexity (~10 services: web, api, celery, flower, postgres, redis, minio, mailhog)
- Requires PostgreSQL and Redis
- SMTP configuration for password resets

#### Ecosystem

- `plane-sdk` on PyPI (official)
- n8n nodes (community)
- Large and growing community
- Self-hosted cloud offering

---

### OpenProject

**GitHub:** `opf/openproject`
**Description:** Enterprise-grade open-source project management (Waterfall, Agile, Hybrid)
**Website:** https://www.openproject.org

#### Stats

- **GitHub Stars:** ~13,000
- **License:** GPL v3 (all code, including Enterprise add-ons)
- **Latest Release:** Active (v15.x series)
- **Languages:** Ruby on Rails backend, AngularJS frontend
- **Deployment:** Docker, native packages

#### API Overview

- **Base URL:** `/api/v3/` (REST API v3)
- **Auth:** Basic auth (`-u user:token`) or session cookie
- **Token generation:** User profile → Account settings → Personal access tokens
- **Pagination:** `?per_page=50&page=2` with `Link` header for next page
- **Throttling:** Configurable per admin

**Endpoints covered (comprehensive):**
- `/api/v3/projects` — Project management
- `/api/v3/work_packages` — Issue/task CRUD (core entity)
- `/api/v3/boards/` — Agile boards (Kanban)
- `/api/v3/types` — Work package types
- `/api/v3/statuses` — Status configuration
- `/api/v3/relations` — Work package relationships (depends-on, duplicates, etc.)
- `/api/v3/watchers` — Watch/user subscriptions
- `/api/v3/custom_fields` — Custom fields
- `/api/v3/my` — Current user operations
- `/api/v3/me` — Authenticated user info

**Webhooks:**
- Administration → API and webhooks → Configure webhooks
- Events: work package created/updated/deleted, project changes
- Payload: JSON with event type and resource details

#### Enterprise vs. Community Edition

Feature                              | Community | Enterprise
------------------------------------|-----------|-----------
Projects                            | All       | All
Work packages (tasks)               | All       | All
Kanban boards (Agile)               | Basic     | Advanced
Gantt charts                        | Basic     | Enhanced
Calendar                            | Yes       | Yes
Time tracking                       | Yes       | Yes
Documents                           | Yes       | Yes
Wikis                               | Yes       | Yes
Custom workflows                    | Limited   | Full
Advanced permissions                | Basic     | Granular
LDAP/SSO                            | Basic     | Full
API                                 | Full REST | Same API
Webhooks                            | Yes       | Yes

**Key insight:** All API-covered features are available in Community edition. Enterprise adds enterprise-grade UI features and more granular permissions.

#### API Quirks

| Quirk | Detail | CelloS Impact |
|-------|--------|---------------|
| Heavy work package model | Work packages have types, statuses, relations, categories, custom fields | Must map to CelloS Task model; type/status mapping required |
| Token-based auth via basic auth | `Authorization: Basic base64(username:token)` — unusual for modern REST | Must handle basic auth correctly |
| Complex relations model | Work packages link via "depends-on", "duplicates", "blocks" | Overkill for CelloS unless needed |
| Custom fields per project | Each project can define its own custom fields | API returns per-project custom field values |
| Board API exists but basic | Agile/Scrum boards available in Community, Advanced boards in Enterprise | Adequate for CelloS |

#### Data Model

```
Project
├── WorkPackages (work_packages) — the primary task entity
│   ├── Type (type) — bug, feature, task, etc.
│   ├── Status (status) — to-do, in-progress, done, etc.
│   ├── Priority
│   ├── Assignees (members)
│   ├── Categories
│   ├── Relations (depends_on, duplicates, blocks)
│   ├── Custom fields
│   ├── Attachments
│   ├── Comments
│   └── Sub-tasks (recursive parent-child)
├── Boards (agile) — Kanban view of work packages
├── Documents
├── Wikis
└── Calendar
```

**Mapping to CelloS:** Possible but requires significant translation. Projects → Workspace, WorkPackages → Tasks. Type/status relations add complexity.

#### Deployment Complexity

- Docker compose: Complex (~15+ services, large JVM dependency)
- Requires PostgreSQL
- Large Docker image (~2GB)
- Well-documented deployment guides

#### Ecosystem

- Full REST API v3 with comprehensive docs
- Webhooks for event notification
- GraphQL API available (advanced)
- Official Python SDK (`openproject-py`)
- 10+ years of enterprise deployment experience

---

### Taiga

**GitHub:** `taigaio/taiga-back`
**Description:** Agile project management for developers and designers (Scrum + Kanban)
**Website:** https://taiga.io

#### Stats

- **GitHub Stars:** ~834 (core repo, monorepo split)
- **License:** AGPL-3.0
- **Latest Release:** v6.10.0 (Apr 20, 2026)
- **Languages:** Python (Django backend), AngularJS frontend
- **Deployment:** Docker compose

#### API Overview

- **Base URL:** `http(s)://<host>/api/v1/`
- **Spec:** https://docs.taiga.io/api.html (extensive, 400+ endpoints)
- **Auth:** Token-based — `POST /api/v1/auth` returns `auth_token`
- **Auth Header:** `Authorization: Bearer <token>`
- **Pagination:** Via `x-disable-pagination: True` header (not query param)
- **Response headers:** `x-paginated`, `x-pagination-count`, `x-pagination-next`

**Endpoints covered (extensive):**
- `/api/v1/projects` — Project CRUD
- `/api/v1/epics` — Epic management
- `/api/v1/userstories` — User stories (main task entity)
- `/api/v1/tasks` — Sub-tasks of user stories
- `/api/v1/issues` — Issues (separate from stories)
- `/api/v1/milestones` — Milestones
- `/api/v1/wiki` — Wiki pages
- `/api/v1/events` — Real-time event streaming
- `/api/v1/importers/trello` — Trello import
- `/api/v1/importers/github` — GitHub import
- `/api/v1/importers/jira` — Jira import

**Webhooks:**
- Per project configuration
- POST-based with signature verification
- Events: milestone, user story, task, issue, wiki page changes
- Logs available with resend capability

**Application Tokens:** OAuth-like flow with JWE-encrypted tokens (more complex than simple bearer tokens)

#### API Quirks

| Quirk | Detail | CelloS Impact |
|-------|--------|---------------|
| OCC (Optimistic Concurrency Control) | Every update needs `version` param; concurrent writes may fail | Extra bookkeeping per object; must track version |
| Pagination via header | `x-disable-pagination: True` instead of query param | Unconventional, must handle header-based pagination |
| Token expiration | Auth tokens expire, need refresh (`POST /api/v1/auth/refresh`) | Must implement retry on expiry |
| Complex application tokens | OAuth-like 3-step flow with JWE encryption | Bearer token from login is sufficient for CelloS |
| Per-type status endpoints | `/api/v1/user-story-statuses`, `/api/v1/task-statuses`, `/api/v1/issue-statuses` | Must discover statuses per work item type |
| Read-only `_extra_info` fields | `assigned_to_extra_info`, `status_extra_info`, `project_extra_info` | Must not write these fields |
| Nested concept model | Epics → User Stories → Tasks (sub-items) | Task mapping must target correct level |

#### Data Model

```
Project
├── Epics — big-picture items
│   └── Related User Stories
├── User Stories — primary task entity (main backlog items)
│   ├── Tasks — sub-items of user stories
│   ├── Statuses (custom per project)
│   ├── Points (story points for sprint planning)
│   ├── Labels
│   ├── Assignees
│   ├── Sprints (milestones)
│   └── Attachments
├── Issues — separate from stories (can be used as tasks)
│   ├── Type (bug, enhancement, etc.)
│   ├── Statuses
│   ├── Priority
│   └── Severity
├── Milestones — time-boxed periods
├── Wiki
└── Tags
```

**Mapping to CelloS:** User Stories are closest to CelloS Tasks. Tasks are sub-items of stories. Issues are separate. Choice of which to map affects the integration:
- **Map to User Stories:** Most feature-rich, supports Kanban, sprint planning
- **Map to Tasks:** Simpler, but only usable under a user story context

#### Deployment Complexity

- Docker compose: Moderate (~7 services: back, front, events, rabbitmq, postgres, redis)
- Requires PostgreSQL, Redis, RabbitMQ for websocket events
- Well-documented installation guides

#### Ecosystem

- `python-taiga` SDK on PyPI
- n8n nodes (community)
- Built-in Trello/GitHub/Jira importers
- Real-time event streaming via WebSocket (`taiga-events`)
- MCP support: `pytaiga-mcp` (community)

---

### Vikunja

**GitHub:** `go-vikunja/vikunja`
**Description:** Self-hosted todo/task management with API and team support
**Website:** https://vikunja.io

#### Stats

- **GitHub Stars:** ~4,500
- **License:** AGPL-3.0-or-later
- **Latest Release:** v2.2.0 (Apr 9, 2026) — 10 security fixes included
- **Languages:** Go (backend), React (frontend)
- **Deployment:** Docker-first, k8s, single binary

#### API Overview

- **Base URL:** `http(s)://<host>/api/v1/`
- **Spec:** Auto-generated from code annotations, available at `/api/v1/docs.json` (OpenAPI)
- **Public instance:** https://try.vikunja.io/api/v1/docs
- **Auth:** API tokens (`Settings → API Tokens` in web UI)
- **Auth Header:** `Authorization: Bearer <token>`
- **Self-hosted also supports:** Username/password → JWT token via `/api/v1/login`
- **Vikunja Cloud:** Token-only (no password auth)

**Endpoints covered (comprehensive):**
- `/api/v1/users/` — User management
- `/api/v1/projects/` — Project CRUD (personal + team)
- `/api/v1/tasks/` — Task CRUD (full featured)
- `/api/v1/task_lists/` — Task lists within projects
- `/api/v1/labels/` — Labels/tags
- `/api/v1/attachments/` — Attachments
- `/api/v1/tasks/{id}/relations/` — Task relations (depends_on, duplicates, relates_to, blocked_by, blocking, duplicated_in, relates_to)
- `/api/v1/webhooks/` — Webhook management
- `/api/v1/filter/` — Filter API
- `/api/v1/oauth/clients/` — OAuth 2.0 provider

#### Webhooks

- Configured per account (not per project)
- POST with HMAC signature (SHA256)
- Event types: task.created, task.updated, task.done, task.deleted, etc.
- Log and resend capability
- Supports multiple webhook URLs
- Per-user configuration

#### API Quirks

| Quirk | Detail | CelloS Impact |
|-------|--------|---------------|
| Token-only auth recommended | JWT available on self-hosted but cloud requires tokens | API tokens don't expire — simpler lifecycle than WeKan/OpenProject |
| Account-level webhooks | Webhooks configured per user, not per project | Must filter events by project |
| Task relations array | Relations include depends_on, duplicated_in, blocked_by, blocking, relates_to | Only needs depends_on → no extra mapping |
| Task lists, not boards/lists | Concept is "task lists within projects" rather than Kanban boards | Must use task lists for CelloS list structure |
| Calendar view native | Built-in calendar + day/week view | Not directly relevant to CelloS |
| CalDAV support | Native CalDAV endpoint for calendar clients | Bonus for CelloS future calendar integration |
| Filter API | Complex filter queries supported via `/api/v1/filter/` | Overkill for CelloS but nice to have |

#### Data Model

```
Project
├── TaskLists (task_lists) — columns/groups
│   └── Tasks (tasks)
│       ├── Predecessors (predecessor_task_ids)
│       ├── Labels (label_ids)
│       ├── Position (float, for ordering)
│       ├── Due date
│       ├── Start date
│       ├── Completion date
│       ├── Description
│       ├── Priority (1-5)
│       ├── Tags
│       ├── Attachments
│       └── Comments
└── Members (members)
```

**Mapping to CelloS:** Very clean. Projects → Workspace, TaskLists → Board/List, Tasks → Tasks. Minimal translation needed — the closest 1:1 fit of any tool studied.

#### Deployment Complexity

- Docker compose: Very simple (single Vikunja API container + PostgreSQL)
- Single binary deployment available
- Configuration via environment variables or config file
- Lightweight: Go binary, ~100MB Docker image

#### Ecosystem

- n8n nodes: `go-vikunja/n8n-vikunja-nodes` (official, maintained by Vikunja team)
- MCP support: `democratize-technology/vikunja-mcp`
- CLI tool: `vikunja-cli` (community)
- Migration tools: Todoist, Todo-txt
- OpenAPI spec auto-generated — always in sync

---

### Leantime

**GitHub:** `Leantime/leantime`
**Description:** Goals-focused project management for non-project managers
**Website:** https://leantime.io

#### Stats

- **GitHub Stars:** ~9,400
- **License:** AGPL-3.0
- **Owner:** Linux Foundation (since ~2025)
- **Latest Release:** v3.8.0 (May 27, 2026)
- **Languages:** PHP (Symfony), React/TypeScript
- **Deployment:** Docker, native PHP

#### API Overview

- **Primary API:** JSON-RPC (single endpoint)
- **Endpoint:** `POST /api/index.php`
- **Auth:** API key via `x-api-key: <key>` header
- **No sessions** — every request authenticated independently

**Request format:**
```
POST /api/index.php
x-api-key: <key>
Content-Type: application/json

{
    "jsonrpc": "2.0",
    "method": "leantime.{module}.{action}",
    "params": { ... },
    "id": 1
}
```

**Methods:**
- `leantime.projects.*` — Project CRUD
- `leantime.tickets.*` — Ticket (task) CRUD
- `leantime.projects.boards.*` — Board/List/Card CRUD
- `leantime.identification.*` — Auth
- `leantime.milestones.*` — Milestones
- `leantime.ideas.*` — Idea management
- `leantime.calendar.*` — Calendar events
- `leantime.users.*` — User management (in progress)

#### API Quirks

| Quirk | Detail | CelloS Impact |
|-------|--------|---------------|
| JSON-RPC for all calls | Single endpoint, method routing via body JSON, not RESTful | Major deviation from standard REST pattern; requires special client |
| No REST endpoints | JSON-RPC replaced REST (v3.8.0 is a migration layer) | Existing REST controllers partially deprecated |
| No webhooks | Event hooks/filters only for PHP plugins, no HTTP webhooks | CelloS must use polling for pull sync |
| Method naming | `leantime.{module}.{action}` — e.g., `leantime.tickets.read` | Not discoverable via standard REST tools |
| Task = Ticket | Primary task entity called "ticket" | Must map to CelloS Task concept |
| Board = Project board | Cards within a project have Kanban boards | Different level than CelloS lists |
| API key lifecycle | API keys created in user settings | No token expiration documented |

#### Data Model

```
Project
├── Boards — Kanban boards within a project
│   └── Tickets (tickets) — task-like cards
│       ├── Status
│       ├── Tags
│       ├── Due date
│       ├── Start date
│       ├── Assigned to
│       ├── Attachments
│       └── Comments
├── Milestones — time periods
├── Issues — bug/problem tracking
├── Ideas — idea management
├── Sprints — configurable sprints
├── Lean Canvas
├── Objectives (OKRs)
└── Research
```

**Mapping to CelloS:** Project boards with tickets. Multiple layers (Project → Board → Tickets → sub-items) but the API is at the Project and Board level.

#### Business-oriented Concepts

Leantime is designed for non-project-managers and includes:
- **Lean Canvas** — business model canvas per project
- **Objectives (OKRs)** — key results tracking
- **Research** — user research documentation
- **Ideas Board** — idea management separate from tasks
- **Goals** — goal trees with KPIs

These are overkill for developer workflow but valuable for product teams.

#### Deployment Complexity

- Docker compose: Moderate (~3 services: app, db, web)
- Requires MySQL/MariaDB
- PHP-based
- 1.5GB Docker image

#### Ecosystem

- Plugin development system (PHP hooks)
- Connector framework for third-party integrations
- MCP support (mentioned in docs)
- Cloud offering available

---

### Planka

**GitHub:** `plankanban/planka`
**Description:** Real-time collaborative Kanban board (Trello-style)
**Website:** https://planka.app

#### Stats

- **GitHub Stars:** ~12,000+
- **License:** Fair-use (PLANKA License) — NOT OSI-approved open source
- **Latest Release:** Active (v2.x)
- **Languages:** Node.js (Express backend), React (frontend)
- **Deployment:** Docker, Helm chart, Kubernetes

#### API Overview

- **Base URL:** `http(s)://<host>/api`
- **Spec:** Swagger UI at `plankanban.github.io/planka/swagger-ui/`
- **Auth:** API token (`Authorization: Bearer <token>`)
- **Real-time:** WebSocket for live updates

**Endpoints covered:**
- `/projects/` — Project CRUD
- `/boards/` — Board CRUD
- `/lists/` — List (column) CRUD
- `/cards/` — Card CRUD
- `/cards/{id}/labels/` — Label management
- `/cards/{id}/attachments/` — Attachments
- `/cards/{id}/checklists/` — Checklists
- `/cards/{id}/members/` — Card members
- `/boards/{id}/custom-fields/` — Custom fields
- `/notification-services/` — Notification/webhook service management
- `/notifications/` — Push notification management

**SDKs:**
- Python: `plankapy` on PyPI
- PHP: `decole/planka-php-sdk` on Packagist
- Postman collection available
- v2 has improved API documentation

#### Webhooks

- **Status:** v2 has webhook configuration in admin UI
- **Issue #1007:** "Add webhooks for main events" — implemented but config moving
- **Community solution:** `c4sti3l/planka-webhook-receiver` (lightweight Go receiver)
- **Events in v2:** card.create, card.update, card.delete, etc.
- **Not yet in stable release** — v2 webhook system still evolving

#### API Quirks

| Quirk | Detail | CelloS Impact |
|-------|--------|---------------|
| Fair-code license | PLANKA License — source visible but not OSI-approved | May affect CelloS project if licensing requires strict open source |
| Webhooks in v2 development | Issue #1007 — working but config being restructured | Not fully stable; polling may be safer for now |
| Hidden REST API | API evolved from WebSocket communication (not designed REST-first) | Some endpoints may not be fully stable |
| Simple card model | Cards have: name, description, members, labels, due dates, checklists, attachments | Very close to CelloS Task model |
| No built-in task types | Unlike Plane/Teiga, no work item types — just cards | Simpler, less feature-rich |
| Board = Kanban board | Single board type, no separate Scrum/Kanban views | Direct Trello equivalent |

#### Data Model

```
Project
├── Boards — Kanban boards
│   └── Lists — card columns
│       └── Cards — the tasks
│           ├── Members (assignees)
│           ├── Labels
│           ├── Due dates
│           ├── Start date
│           ├── Description (Markdown)
│           ├── Checklists
│           ├── Comments
│           ├── Attachments
│           ├── Custom fields
│           └── Time tracking
├── Custom field groups
└── Notification services
```

**Mapping to CelloS:** Very clean 1:1 mapping. Projects → Workspace, Boards → List, Cards → Tasks. Simplest structure after Vikunja.

#### License Detail

The PLANKA License is a Fair-code / source-available license (not OSI-approved):
- Source code is visible
- Free to use, modify, and distribute
- Restrictions on commercial competition ("you cannot sell Planka as a service")
- `.pe` files are PLANKA Pro/Enterprise features (gated)
- Based on the Sustainable Use License (same as n8n)

For self-hosted CelloS use: **No problem.** The Fair-code restriction targets competing cloud services, not internal/self-hosted usage.

#### Deployment Complexity

- Docker compose: Simple (api, nginx, postgrest containers)
- Requires PostgreSQL
- Lightweight compared to OpenProject/Plane

---

### Kanboard

**GitHub:** `kanboard/kanboard`
**Description:** Simple Kanban project management
**Website:** https://kanboard.org

#### Stats

- **GitHub Stars:** ~9,600
- **License:** MIT
- **Status:** In maintenance mode (confirmed by maintainers)
- **Latest Release:** Stable but infrequent updates
- **Languages:** PHP (single monolithic application)
- **Deployment:** Docker, PHAR, native PHP

#### API Overview

- **Base URL:** `/jsonrpc.php`
- **Auth:** Basic auth with API key as password
- **Protocol:** JSON-RPC 2.0 (similar to Leantime)
- **Methods:** `createTask`, `getTask`, `updateTask`, `moveTask`, `getColumns`, `getLists`, etc.

**Endpoints covered:**
- Task CRUD via JSON-RPC methods
- Board/List/Column management
- User management
- Calendar views
- File attachments

#### Key Facts

- **Maintenance mode confirmed:** No major new features expected
- **Codebase is stable:** Well-tested, minimal breaking changes
- **Simple API:** Few methods, straightforward usage
- **No webhooks**
- **Concepts:** Projects → Columns → Lists → Tasks (simple, flat)

**Not recommended for new integrations** due to maintenance mode, but the API is simple enough for a basic connector.

---

## Comparison Matrix

Feature                          | WeKan      | Plane       | OpenProject | Taiga       | Vikunja     | Leantime    | Planka      | Kanboard
---------------------------------|------------|-------------|-------------|-------------|-------------|-------------|-------------|----------
License                          | MIT        | AGPLv3      | GPL v3      | AGPL-3.0    | AGPLv3      | AGPLv3      | Fair-use    | MIT
Stars                            | ~21k       | ~51k        | ~13k        | ~834        | ~4.5k       | ~9.4k       | ~12k        | ~9.6k
REST API                         | Yes        | Yes         | Yes         | Yes         | Yes         | No (JSON-RPC)| Yes         | No (JSON-RPC)
API Auth                         | Bearer     | API Key     | Basic       | Bearer      | Bearer      | API Key     | Bearer      | Basic/Auth
Token Expiration                 | Yes        | API Key: No | Token: No   | Yes         | API Token: No| API Key: No | Bearer: No  | API: No
Webhooks                         | No         | Yes (bugs)  | Yes         | Yes         | Yes         | No          | v2 (beta)   | No
OpenAPI / Swagger                | Yes        | Partial     | Yes         | Yes         | Yes         | No          | Yes         | No
Pagination                       | Query param| Cursor      | Link header | Header      | Query param | N/A         | Query param | N/A
Rate Limiting                    | Unknown    | 60/min      | Configurable| Configurable| Configurable| Unknown     | Unknown     | None
Concepts                         | Boards→Lists→Cards | Workspace→Projects→Issues | Projects→WorkPackages | Projects→Epics→Stories→Tasks | Projects→Lists→Tasks | Projects→Boards→Tickets | Projects→Boards→Lists→Cards | Projects→Columns→Lists→Tasks
Kanban Boards                    | Native     | Native      | Yes         | Yes         | Yes         | Yes         | Native      | Native
Scrum / Sprints                  | No         | Cycles      | Yes         | Yes         | No          | Yes         | No          | No
Custom Fields                    | Limited    | Yes         | Yes         | Yes         | Yes         | Yes         | Yes         | Yes
Comments                         | Yes        | Yes         | Yes         | Yes         | Yes         | Yes         | Yes         | Yes
Attachments                      | Yes        | Yes         | Yes         | Yes         | Yes         | Yes         | Yes         | Yes
Checklists                       | Yes        | Yes         | No          | No          | Yes         | Yes         | Yes         | Yes
Time Tracking                    | Basic      | Yes         | Yes         | Yes         | Basic       | Yes         | Yes         | Yes
Labels / Tags                    | Yes        | Labels      | Categories  | Labels      | Labels      | Tags        | Labels      | Labels
Realtime Updates                 | Pusher     | WebSocket   | No          | WebSocket   | No          | No          | WebSocket   | No
Python SDK                       | python-wekan| plane-sdk   | openproject-py| python-taiga| Manual      | Manual      | plankapy    | Manual
PHP SDK                          | —          | —           | —           | —           | —           | Plugin API  | planka-php-sdk| —
n8n Nodes                        | Yes        | Yes         | Yes         | Yes         | Yes         | Yes         | No          | Yes
MCP Support                      | No         | No          | No          | pytaiga-mcp | vikunja-mcp | (in docs)   | mcp-planka  | No
Deployment Difficulty            | Easy       | Medium      | Medium      | Medium      | Easy        | Medium      | Easy        | Easy
Licensing Risk                   | Low (MIT)  | Low (AGPLv3)| Low (GPL v3)| Low (AGPLv3)| Low (AGPLv3)| Low (AGPLv3)| Medium (Fair-use)| Low (MIT)

---

## API Quirks Summary

### WeKan
- Session-based auth via `POST /users/login` — sends plaintext password over HTTPS
- API version embedded in URL (`/api/v9.57/`) per instance
- Inconsistent content types: some endpoints JSON, others form-urlencoded
- No webhooks — polling only
- No API key generation — must use user credentials
- Auth tokens have `expiresAt` — must implement refresh

### Plane
- Webhooks have known bugs: duplicate POSTs (#6848), API events not triggering (#6746)
- Rate limited to 60 req/min per API key
- Cursor-based pagination in non-standard format: `value:offset:is_prev`
- OAuth 2.0 less tested than API key auth
- Some endpoints still missing (integrations #8906, members #8459)

### OpenProject
- Token-based auth via Basic auth header (unusual: `Authorization: Basic base64(user:token)`)
- Heavy work package model with types, statuses, relations, custom fields
- Board API exists but Basic in Community edition

### Taiga
- Optimistic Concurrency Control — every update needs `version` parameter
- Pagination via `x-disable-pagination: True` header (not query param)
- Auth tokens expire — need refresh
- Per-type status endpoints (separate endpoints for user story, task, and issue statuses)
- OAuth-like application tokens with JWE encryption
- Nested concept model (Epics → User Stories → Tasks)

### Vikunja
- API tokens do not expire (recommended auth method)
- Self-hosted also supports JWT via username/password login
- Account-level webhooks (not per-project)
- Task relations include 6 relationship types
- OpenAPI spec auto-generated from code (always in sync)

### Leantime
- Single JSON-RPC endpoint: `POST /api/index.php` with method routing in body
- No REST endpoints (migrating FROM REST)
- No webhooks
- No sessions — each request independently authenticated

### Planka
- Fair-code license (not OSI-approved)
- Webhooks for v2 in development (Issue #1007)
- API evolved from WebSocket patterns — some endpoints may not be fully stable
- Simple card model with no work item types

### Kanboard
- JSON-RPC 2.0 protocol (single endpoint)
- In maintenance mode — no major features expected
- Simple API surface — stable but limited

---

## Concept Mapping Guide

### CelloS Task Model

```
Task
├── id, title, description, status
├── priority, labels/tags
├── due_date, created_at, updated_at
├── subtasks (nested)
└── attachments, comments
```

### Mapping to Each Tool

**WeKan (Best Fit)**
```
CelloS → WeKan
Workspace    → Board
List/Board   → List
Task         → Card
Subtasks     → Cards in other lists
Labels       → Labels
Priority     → Due date / custom properties
```

**Vikunja (Best Fit)**
```
CelloS → Vikunja
Workspace  → Project
List/Board → TaskList
Task       → Task
Subtasks   → Predecessor relations or child tasks
Labels     → Labels
Priority   → Priority (1-5)
```

**Planka (Good Fit)**
```
CelloS → Planka
Workspace  → Project
List/Board → List
Task       → Card
Subtasks   → Card descriptions or linked cards
Labels     → Labels
Priority   → Labels or custom fields
```

**Plane (Complex)**
```
CelloS → Plane
Workspace  → Project
List/Board → Custom view or module
Task       → Issue
Subtasks   → Sub-issue links
Labels     → Labels
Priority   → Priority field
```

**OpenProject (Complex)**
```
CelloS → OpenProject
Workspace  → Project
List/Board → Agile board view
Task       → Work Package
Subtasks   → Parent-child relations
Labels     → Categories
Priority   → Priority field
```

**Taiga (Complex)**
```
CelloS → Taiga
Workspace  → Project
List/Board → Kanban view
Task       → User Story (OR Task as sub-item)
Subtasks   → Tasks (if mapping to User Stories)
Labels     → Tags
Priority   → Priority field
```

**Leantime (Moderate)**
```
CelloS → Leantime
Workspace  → Project
List/Board → Board (within project)
Task       → Ticket
Subtasks   → Sub-tickets
Labels     → Tags
Priority   → Priority field
```

---

## Recommendations for CelloS

### Top 3 for Integration Prioritization

| Priority | Tool | Rationale |
|----------|------|-----------|
| **1** | **Vikunja** | Cleanest REST API with OpenAPI spec, API tokens don't expire, native webhooks with signature, simple task-centric data model, Go binary (lightweight), n8n + MCP support, AGPLv3 |
| **2** | **WeKan** | Near 1:1 Trello API mapping (existing celloS connector pattern), MIT license (no copyleft concerns), ~660 releases showing stability, huge community, Docker-first |
| **3** | **Plane** | Best developer-experience PM tool, comprehensive APIs with Python SDK, modern stack, large and growing community, webhooks with documented bugs (manageable with polling fallback) |

### Tool-Specific Integration Notes

**Vikunja should be built with:**
- API token auth (no expiration lifecycle)
- Webhooks for push sync (with retry on failure)
- Polling as fallback (in case webhook delivery fails)
- Task IDs linked via `source_id` field
- Labels mapped 1:1 to Vikunja labels

**WeKan should be built with:**
- Session token auth with expiration handling
- Polling for pull sync (no webhooks available)
- Board ID linked via custom properties on cards
- API version discovery on first sync
- Username/password stored securely for login

**Plane should be built with:**
- API key auth (no expiration)
- Polled sync with rate limit awareness (60/min)
- Webhooks for immediate notification (but don't rely on them)
- Issue IDs linked via source_id
- Proper cursor pagination handling

### Anti-Priorities (Don't Build Yet)

| Tool | Why |
|------|-----|
| **OpenProject** | Heavy, complex model; more suited for enterprise use than lightweight CelloS sync |
| **Taiga** | OCC bookkeeping + nested Epics→Stories→Tasks model adds complexity |
| **Leantime** | JSON-RPC, no webhooks, business-oriented concepts mismatch developer workflow |
| **Planka** | Fair-code license caveat; v2 webhooks still evolving |
| **Kanboard** | In maintenance mode; limited long-term viability |

---

## Appendix: Sources

- WeKan changelog: `github.com/wekan/wekan/blob/main/CHANGELOG.md`
- WeKan REST API: `github.com/wekan/wekan/wiki/REST-API-Boards`
- Plane API docs: `developers.plane.so/api-reference/introduction`
- Plane webhook issues: `github.com/makeplane/plane/issues/6848`, `6746`, `7249`
- OpenProject API: `www.openproject.org/docs/api/`
- Taiga API: `docs.taiga.io/api.html`
- Vikunja API: `vikunja.io/docs/api-documentation/`
- Leantime API: `docs.leantime.io/api/usage`
- Planka API: `docs.planka.cloud/docs/category/api-reference/`
- Kanboard docs: `docs.kanboard.org/user/api.html`
- Focalboard maintenance: `github.com/mattermost-community/focalboard/issues/4983`
- Planka license: `github.com/plankanban/planka/blob/master/LICENSES/PLANKA%20License%20Guide%20EN.md`
