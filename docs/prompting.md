# Prompting

CelloS prompts are built around task lifecycle mode, agent role, and task scope. Parent tasks and child tasks use the same lifecycle.

```text
task exists
-> planning prompt
-> plan saved to task
-> human revises or approves
-> execution prompt
-> result saved
```

## Prompt Stack

Each worker prompt should stay focused and use this order:

```text
CelloS operating rules
Mode instructions
Role instructions
Task metadata
Task prompt / approved scope
Output format
Final instructions
```

Planning prompts include task comments and research results because planning needs the available discussion and completed research to produce a better plan. Execution prompts stay narrower and do not automatically include comments, parent task history, attempt logs, dependency logs, or broad project history. If execution context matters, the approved plan should include it.

## Planning Mode

Planning mode is read-only.

Planning agents may:

- clarify the objective,
- decompose complicated work,
- propose child tasks,
- propose prerequisite research tasks,
- define acceptance criteria,
- identify risks and unknowns.

Planning agents must not:

- create tasks directly,
- edit files,
- run commands,
- perform research directly,
- execute any part of the plan.

If research is needed before a reliable plan can be written, the planning result should request a research task as part of the proposed plan.

Planning prompts may include:

- all comments on the current task,
- system comments containing completed research results,
- the current task prompt or previous plan.

Planning prompts should not include full attempt logs or unrelated parent history.

## Execution Mode

Execution mode acts only on an approved plan.

Execution agents may:

- perform the approved work,
- create child tasks if the approved plan explicitly says to create them,
- create prerequisite research tasks if the approved plan explicitly says to create them,
- return a change request if the approved plan cannot be completed.

Execution agents must not:

- expand the approved scope,
- redesign the plan,
- create extra tasks that were not approved,
- perform unrelated cleanup.

## Research Tasks

Research is a normal task type. It should usually be created by approved execution of a parent task that determined research was needed.

The default safe flow is:

```text
A is planned
-> A plan requests research task R
-> human approves A
-> A execution creates R
-> R waits for approval
-> R executes after approval
-> R result is added to A as a system comment
-> A becomes eligible for replanning after R completes
```

CelloS can optionally pre-approve research tasks created by approved execution. This is controlled by:

```json
{
  "approvals": {
    "preapprove_research_tasks": false
  }
}
```

When `preapprove_research_tasks` is `true`, a created research task that asks for `approved` status may be created as `approved`. When it is `false`, that same task is created as `needs_approval`.

When a research dependency completes, CelloS stores the result on the research task and also adds a system comment to each direct dependent task:

```text
Research Results from TASK_ID - Task title

<result summary>
```

That system comment is included in the dependent task's next planning prompt under `Research Results`.

## Structured Task Creation

Execution agents request task creation with a fenced JSON block:

```json
{
  "actions": [
    {
      "type": "create_task",
      "title": "Research API constraints",
      "role": "researcher",
      "task_type": "research",
      "prompt": "Research the API constraints and report findings.",
      "status": "approved",
      "blocks_parent": true
    }
  ]
}
```

`blocks_parent` means the parent task depends on the created task. The parent becomes blocked until the dependency completes, then it becomes eligible for planning again.
