# Vikunja smoke test report: anomalies, failures, and issues

Smoke test document:

- `/home/james/workspace/cellos/docs/vikunja-smoke-test.md`

Run prefix:

- `[vikunja smoke 2026-06-30 04:32]`

Overall result:

- Smoke test completed through Step 7e.
- No hard functional failures were observed.
- Several anomalies/quirks were observed and should be reviewed.

## Summary

The core connector behaviors passed:

- Cellos -> Vikunja task push worked.
- Cellos -> Vikunja task update worked.
- Vikunja -> Cellos pull worked.
- Pull idempotence worked.
- Local comment export to Vikunja worked.
- Push idempotence for comments worked.
- Remote Vikunja comment import worked.
- Pull idempotence for comments worked.

Observed issues were mostly around display normalization and reporting clarity.

## Anomaly 1: Cellos local display strips smoke-test title prefix

### Observed

A local Cellos task was created with this title:

```bash
cellos add-task "[vikunja smoke 2026-06-30 04:32] Local push test" -d "Created in Cellos to verify push into Vikunja." -r engineer
```

Cellos reported:

```text
✓ Created task e93a6c2329e7:  Local push test
  Role: engineer | Type: implementation | Status: draft
```

`cellos status` also displayed:

```text
Local push test
```

The smoke-test prefix was not shown locally.

However, after push, Vikunja displayed the full expected title:

```text
[vikunja smoke 2026-06-30 04:32] Local push test
```

The same pattern appeared for the remote-created task:

- Vikunja title: `[vikunja smoke 2026-06-30 04:32] Remote pull test`
- Cellos display after pull: `Remote pull test`

### Impact

This did not break sync, but it makes smoke-test verification confusing because the document expects exact title matching while Cellos local display appears to normalize or strip the bracketed prefix.

### Suggested review

Decide whether this is intended behavior.

If intended:

- update the smoke test doc to mention local title normalization.

If unintended:

- inspect task title parsing/display behavior in the Cellos CLI.

Likely areas:

- `cellos/cli.py`
- task creation/display formatting
- any title-prefix or metadata parsing logic

## Anomaly 2: Local comment push reports `Items updated: 0` even though export succeeds

### Observed

Step 7a added a local Cellos comment and pushed to Vikunja:

```bash
cellos comment e93a6c2329e7 -m "Smoke-test local comment to verify Vikunja sync."
cellos pmcon sync vikunja --push
```

Output:

```text
✓ Comment added to e93a6c2329e7
  ⚠️ Attention triggered: Human commented
✓ Push complete
  Items created: 0
  Items updated: 0
```

This looked suspicious because Step 7b expected the comment to appear in Vikunja.

After checking the browser UI, the comment was visible on the Vikunja task:

```text
Smoke-test local comment to verify Vikunja sync.
```

Step 7c then re-ran push and verified via browser DOM that the comment appeared exactly once:

```json
{"count":1,"snippets":["Smoke-test local comment to verify Vikunja sync."]}
```

### Impact

Functional sync passed, but reporting is misleading.

`Items updated: 0` does not communicate that a comment was exported. A tester could reasonably interpret this as "nothing changed," even though the local comment appeared remotely.

### Suggested review

Clarify push reporting for comment sync.

Options:

- add a separate `Comments exported` counter,
- include comment export in `Items updated`, or
- document that comment export is not reflected in item update counts.

Likely areas:

- `cellos/integrations/vikunja/provider.py`
- `cellos/integrations/vikunja/client.py`
- `cellos/cli.py` sync result formatting

Specific questions:

1. Does outbound comment sync have its own result counter internally?
2. Are exported comments intentionally excluded from `Items updated`?
3. Could `pmcon sync vikunja --push` report comment export counts explicitly?

## Anomaly 3: Vikunja-origin descriptions/comments are HTML-wrapped in Cellos

### Observed

A remote Vikunja task was created with description:

```text
Created in Vikunja to verify pull into Cellos.
```

After pull, Cellos detail showed:

```text
Details: <p>Created in Vikunja to verify pull into Cellos.</p>
```

A remote Vikunja comment was added:

```text
Smoke-test remote comment to verify Cellos sync.
```

After pull, Cellos detail showed:

```text
System: <p>Smoke-test remote comment to verify Cellos sync.</p>
```

### Impact

Sync functionally passed, but local output contains raw HTML wrappers from Vikunja-origin content.

This may be acceptable if Cellos stores/render remote markdown/html as-is, but it is visually inconsistent with local-origin comments/details.

### Suggested review

Decide whether Cellos should:

- preserve Vikunja HTML exactly,
- strip simple HTML wrappers for CLI display,
- convert HTML to markdown/plain text on import,
- or document that Vikunja-origin content may be HTML-wrapped.

Likely areas:

- Vikunja pull/import conversion in `cellos/integrations/vikunja/provider.py`
- Vikunja API client response handling in `cellos/integrations/vikunja/client.py`
- CLI detail rendering in `cellos/cli.py`

## Anomaly 4: Pull normalized pushed task status from `draft ⚠️` to `approved`

### Observed

The local pushed task began as:

```text
e93a6c2329e7 | draft ⚠️ | engineer | Local push test
```

After pulling from Vikunja during Step 7d, the task detail showed:

```text
Status: approved
```

Pull output included:

```text
Statuses changed: 1
```

### Impact

This is not considered a failure because the smoke test document explicitly notes:

> a local Cellos `draft` task pushed into Vikunja `To-Do` may later appear locally as `approved` after pull; that is current connector status-normalization behavior and is not by itself a smoke-test failure

Still, it is worth noting because it changes local task state during the smoke test.

### Suggested review

No immediate fix needed if this is intended.

If the behavior surprises users, consider making status normalization more visible in sync output.

## Non-issue: Direct task URL uses internal task ID, not visible `#N`

### Observed

The Vikunja kanban card displayed visible task number:

```text
#1
```

Navigating to:

```text
http://10.1.3.35:3456/tasks/1
```

returned a 404.

DOM inspection showed the real internal task ID was:

```text
data-task-id="37"
```

Navigating to:

```text
http://10.1.3.35:3456/tasks/37
```

opened the task correctly.

### Impact

This was a tester/navigation issue, not a connector bug.

The visible Vikunja task number is not the same as the route ID.

### Suggested doc note

If browser-based smoke verification requires opening a task directly, mention that the URL route may require Vikunja's internal task ID, not the displayed `#N` number.

## Final smoke-test status

Passed:

- Step 1: initialize local Cellos state
- Step 2: setup Vikunja integration
- Step 3: verify reusable Vikunja labels
- Step 4: verify integration status
- Step 5a: create local task
- Step 5b: push local task to Vikunja
- Step 5c: verify pushed task in Vikunja
- Step 5d: update local task and push
- Step 5e: verify update in Vikunja
- Step 6a: create remote Vikunja task
- Step 6b: pull remote task into Cellos
- Step 6c: verify imported local details
- Step 6d: re-run pull for idempotence
- Step 7a: add local comment and push
- Step 7b: verify local comment in Vikunja
- Step 7c: re-run push for outbound comment idempotence
- Step 7d: add remote comment and pull
- Step 7e: re-run pull for inbound comment idempotence

No hard failures observed.

Highest-priority issue to clean up:

- push reporting should make comment export visible; `Items updated: 0` is misleading when a local comment is successfully exported.
