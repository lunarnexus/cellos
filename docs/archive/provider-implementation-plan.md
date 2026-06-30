# Open-Source PM Provider Implementation Plan

> Archived: this plan predates the implemented Vikunja connector and is retained for provider-strategy history.

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the abandoned Trello direction with a clean provider strategy for WeKan, Plane, and OpenProject while preserving CelloS's generic PM integration core.

**Architecture:** Keep `cellos/integrations/base.py` and `cellos/integrations/registry.py` as the generic provider core. Implement each PM tool as an isolated package under `cellos/integrations/<provider>/`. Start with WeKan as the first real provider because it is the simplest board/list/card fit.

**Tech Stack:** Python, Pydantic, aiohttp/httpx, SQLite, pytest.

---

## Phase 0: Stabilize the Trello removal

### Task 0.1
- remove Trello-specific docs/tests/code
- keep generic provider contract and registry
- verify `pmcon list` still works with the example provider

### Task 0.2
- replace Trello-specific schema/config naming with generic names where practical
- verify generic smoke test still passes

---

## Phase 1: Evaluate provider capabilities

### Task 1.1 — WeKan capability check
- auth model
- API shape
- board/list/card/comment support
- webhook/event support
- self-hosting assumptions

### Task 1.2 — Plane capability check
- auth model
- issue/project/comment/workflow support
- webhook/event support
- required field mappings

### Task 1.3 — OpenProject capability check
- auth model
- work package/board/comment/status support
- webhook/event support
- required configuration complexity

**Deliverable:** a short comparison matrix in docs.

---

## Phase 2: Finalize generic provider contract

### Task 2.1
Define the minimum provider lifecycle for the first real connectors:
- `setup()`
- `status()`
- `sync()`
- optional event subscription hooks if the provider supports webhooks

### Task 2.2
Define generic normalized concepts:
- external target ID
- external item mapping
- status mapping
- comment import/export

### Task 2.3
Define explicit source-of-truth rules before coding the first provider.

---

## Phase 3: Implement WeKan first

### Task 3.1
Create `cellos/integrations/wekan/`

### Task 3.2
Implement API client and models

### Task 3.3
Implement provider setup/status/sync

### Task 3.4
Add focused tests:
- provider loading
- setup/status behavior
- sync behavior
- CLI integration via `pmcon`

---

## Phase 4: Reassess before Plane/OpenProject

After WeKan works:
- review whether the provider contract is actually good enough
- patch the generic interface if WeKan exposed missing seams
- only then begin Plane

---

## Key anti-goals

- do not reintroduce provider-specific rules into core
- do not build a second giant Trello-style cleanup cycle
- do not add half-finished provider code for all three at once

## Recommendation

Implement **WeKan first**, then re-evaluate the provider contract before touching Plane or OpenProject.
