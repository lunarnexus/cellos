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

Task intake details, the working plan, the approved execution scope, and the ongoing conversation are related but not identical. CelloS should keep them conceptually separate even when some current implementations still store parts of that information together.

## Planning Mode

Planning mode is read-only.

Planning agents may:

- clarify the objective,
- ask clarifying questions in task comments/conversation,
- decompose complicated work,
- propose child tasks,
- propose prerequisite research tasks,
- revise earlier decomposition when research changes the shape of the problem,
- define acceptance criteria,
- identify risks and unknowns.

Planning agents must not:

- create tasks directly,
- edit files,
- run commands,
- perform research directly,
- execute any part of the plan.

## Execution Mode

Execution agents perform the approved work.

Execution agents may:

- edit files within the approved scope,
- run commands within the approved scope,
- perform research within the approved scope,
- attempt limited troubleshooting within the approved task boundary.

Execution agents must not:

- expand scope beyond the approved plan,
- create tasks without explicit authorization,
- silently change the approved approach.

If the task cannot be completed as approved, the agent should report failure or request a change.

## Prompt Profiles

Prompt profiles are stored in `promptprofiles.json` and loaded at each heartbeat. They define:

- role instructions (per-role guidance),
- mode instructions (per-mode behavior),
- output sections (what the agent should include in its response).

Changes to prompt profiles take effect on the next `cellos run`.

## See Also

- `docs/communication.md` — artifact formats
- `docs/roles-and-lifecycle.md` — planning vs execution lifecycle
- `cellos/prompt_builder.py` — prompt construction code
- `cellos/config.py` — prompt profile loading
