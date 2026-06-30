# Connector Authoring Guide

This document explains how to add a new PM connector to CelloS without copying provider-specific internals into the core.

## Design Rules

CelloS uses a **generic provider core** plus **provider-owned implementation packages**.

### Core may know
- provider names
- provider descriptions
- provider lifecycle methods
- provider registry discovery
- generic scheduler hooks
- generic sync/status DTOs

### Core may not know
- provider-specific board/list names
- provider-specific workflow state names
- provider-specific team/project semantics
- provider-specific REST payloads
- provider-specific setup rules

Provider-specific behavior belongs under `cellos/integrations/<provider>/`.

---

## Required Package Shape

A connector is discovered from this package structure:

```text
cellos/integrations/<provider>/
  __init__.py
  provider.py
```

The registry scans packages under `cellos.integrations.*` and imports:

```text
cellos.integrations.<provider>.provider
```

Source of truth:
- `cellos/integrations/registry.py`

---

## Required Provider Class

Your `provider.py` must define a **concrete** subclass of `IntegrationProvider`.

Minimal shape:

```python
from cellos.integrations.base import IntegrationProvider, IntegrationStatus, SetupResult, SyncDelta


class MyProvider(IntegrationProvider):
    PROVIDER_NAME = "my-provider"
    PROVIDER_DESCRIPTION = "My PM connector"

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    async def is_configured(self) -> bool:
        ...

    async def setup(self, clean: bool = False) -> SetupResult:
        ...

    async def status(self) -> IntegrationStatus:
        ...

    async def sync(self, push: bool = True, pull: bool = True) -> SyncDelta:
        ...

    async def auto_push(self) -> SyncDelta:
        ...

    async def auto_pull_maybe(self, pull_interval_seconds: int) -> SyncDelta:
        ...
```

Source of truth:
- `cellos/integrations/base.py`

---

## Required Metadata

Each provider class must define:

- `PROVIDER_NAME`: short stable identifier, used in CLI commands
- `PROVIDER_DESCRIPTION`: human-readable description for `pmcon list`

Example:

```python
PROVIDER_NAME = "linear"
PROVIDER_DESCRIPTION = "Linear issue sync"
```

---

## Setup Contract

`setup()` returns a `SetupResult`.

```python
@dataclass
class SetupResult:
    target_id: str
    mappings: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
```

Use it like this:
- `target_id`: board/project/workspace ID or equivalent
- `mappings`: workflow state or list mappings discovered during setup
- `details`: extra metadata that may be helpful for debugging or future UI

Examples:
- Board-style providers: `target_id=board_id`, `mappings={"backlog": "list123"}`
- Issue-style providers: `target_id=project_id`, `mappings={"todo": "stateA", "done": "stateB"}`

---

## Status Contract

`status()` returns `IntegrationStatus` for generic CLI rendering.

Core expects:
- provider name
- whether the provider is configured
- whether credentials are configured
- optional target identifier
- optional provider details map

Keep details generic enough for display, but the provider owns their meaning.

---

## Sync Contract

`sync()` returns `SyncDelta`.

Generic fields:
- `items_created`
- `items_updated`
- `items_moved`
- `comments_imported`
- `statuses_changed`
- `errors`

Not every connector must use every field equally, but the result should remain understandable from a generic CLI surface.

---

## Config Guidance

Provider-specific config belongs to the provider.

Current config model supports this generically:
- `ProviderConfig` allows provider-specific extra fields
- `IntegrationsConfig` stores providers under `providers`
- compatibility access via `config.integrations.<provider>` still works

Examples of provider-owned fields:
- `board_id`
- `project_id`
- `team_id`
- `workspace_id`
- `workflow_state_map`

Do **not** add shared core logic that assumes any provider's field names are canonical.

Source of truth:
- `cellos/config.py`

---

## Discovery and CLI Behavior

If your provider imports successfully and defines a valid concrete provider class:
- it will be discoverable by the registry
- it will appear in `cellos pmcon list`
- it can be loaded by `cellos pmcon setup <provider>` and related commands

Source of truth:
- `cellos/integrations/registry.py`
- `cellos/cli.py`

---

## Example Provider

A minimal reference implementation exists here:

- `cellos/integrations/example/provider.py`

Use it as a template for the smallest valid connector.

---

## New Connector Checklist

1. Create `cellos/integrations/<provider>/`
2. Add `__init__.py`
3. Add `provider.py`
4. Subclass `IntegrationProvider`
5. Set `PROVIDER_NAME` and `PROVIDER_DESCRIPTION`
6. Implement `is_configured`, `setup`, `status`, `sync`, `auto_push`, `auto_pull_maybe`
7. Keep provider-specific API/client logic under the provider package
8. Add provider-specific tests
9. Run provider contract tests
10. Verify `cellos pmcon list`
11. Verify `cellos pmcon setup <provider>`
12. Verify scheduler behavior if auto-sync is supported

---

## Recommended File Layout for Real Connectors

```text
cellos/integrations/<provider>/
  __init__.py
  provider.py
  client.py          # API wrapper if needed
  models.py          # provider response/request models if needed
  mapper.py          # state/status mapping helpers if needed
  sync_service.py    # provider-owned operational sync logic if needed
```

Not every connector needs all of these files. Keep it small.

---

## Implementation Principle

**Core stays generic. Provider packages own provider behavior.**

If a change requires the core to learn provider-specific domain rules, the design is probably wrong.

---

## Vikunja Connector Notes

The repo now includes a provider-owned Vikunja connector under:

```text
cellos/integrations/vikunja/
```

### Required environment

- `VIKUNJA_BASE_URL` — full API base URL, for example `http://host:3456/api/v1`
- `VIKUNJA_API_TOKEN` — bearer token for the Vikunja user

Important: `VIKUNJA_BASE_URL` must include the `/api/v1` prefix. The provider does not append it automatically.

### Required provider config

Example:

```yaml
integrations:
  providers:
    vikunja:
      project_id: "1"
      view_id: "4"
      bucket_map:
        to-do: "1"
        doing: "2"
        done: "3"
```

### Sync behavior

- **Push**: creates remote tasks for unmapped local tasks and updates mapped remote tasks.
- **Pull**: imports unmapped remote project tasks into CelloS and updates mapped local task status from Vikunja.
- **Comments**: exports local comments to Vikunja and imports remote task comments into local `task_comments` with duplicate prevention.

### Vikunja-specific semantics

- Kanban buckets are **view-scoped** in Vikunja.
- The authoritative write path for moving a card between buckets is:
  - `POST /projects/{project}/views/{view}/buckets/{bucket}/tasks`
- The authoritative read path for bucket placement is task fetches with:
  - `expand=buckets`

Do not rely on raw `task.bucket_id` alone for status reconstruction. On the live test instance used during implementation, `bucket_id` remained `0` even when `expand=buckets` showed the correct kanban bucket.
