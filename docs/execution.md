# CelloS — Execution Plan

## 4. EXECUTION PLAN — How to Build This

### Phase 0: Foundation (Week 1-2)

**Goal:** Core orchestration engine, no UI, just the plumbing.

```
cellos/
├── cellos/
│   ├── __init__.py
│   ├── cli.py              # CLI entry point (click)
│   ├── config.py           # Config loading (pydantic-settings)
│   ├── agent.py            # Base Agent class
│   ├── conductor.py        # Conductor agent (plan generation)
│   ├── architect.py        # Architect agent (plan generation)
│   ├── engineer.py         # Engineer agent (task execution)
│   ├── test_engineer.py    # Test agent
│   ├── pm.py               # Project Manager heartbeat
│   ├── task.py             # Task model + schema
│   ├── plan.py             # Plan model + approval gates
│   ├── memory.py           # Project memory (lessons learned)
│   ├── escalation.py       # Escalation chain logic
│   ├── loop_detector.py    # Prevent infinite retry loops
│   └── skills/             # Skill loading system
├── skills/
│   └── default/            # Default skills
├── tests/
│   └── test_orchestration.py
├── pyproject.toml
└── README.md
```

### Phase 0: Core Engine (Week 1-2)

**Goal:** The Conductor and the Task/Plan models. No UI yet.

**Tasks:**
1.  Set up project structure with pyproject.toml
2.  Implement `Task` model — status, dependencies, agent type, specs, results
3.  Implement `Plan` model — goals, directives, approval gates, phases
4.  Implement base `Agent` class — model routing, tool loading, skill loading
5.  **Implement `Conductor`** — takes user request → generates high-level plan (using **Claude Opus** or **GPT-4.5**)
6.  Implement `Architect` — takes approved plan → generates architecture
7.  Implement `Engineer` — takes task spec → executes → reports results
8.  Implement `TaskQueue` — Redis-based, with dependency resolution
9.  Implement `PM Heartbeat` — periodic status checks, hung task detection
10. Implement `Escalation` — failure propagation up the chain
11. Implement `LoopDetector` — track retry counts, prevent infinite loops
12. Write tests for each component

**Tools:** Opencode (primary coding agent), VSCode (editor), Hermes (for research/review)

### Phase 1: PM Adapters (Week 3-4)

**Goal:** CelloS can read tasks from Trello/Teams/Notion/Jira/Azure DevOps/OpenProject/Asana and push plans back.

**Tasks:**
1.  Implement Trello adapter — read cards, create new lists (for plans), create cards (for subtasks).
2.  Implement MS Teams adapter — send "Plan for Review" Adaptive Cards, listen for click events.
3.  Implement Notion adapter — create database entries, sync task status.
4.  Implement Jira adapter — create issues, update status, transitions.
5.  Implement Azure DevOps adapter — work items, approvals.
6.  Implement OpenProject adapter — tasks, boards.
7.  Implement Asana adapter — projects, tasks, sections.
8.  Implement approval logic — when user moves a card or clicks "Approve" in any tool, signal the engine.
9.  Implement task push — when a plan is generated, create items in the selected PM tool.
10. Implement "Edit Plan" flow — user edits a task in any PM tool, CelloS updates the plan and regenerates subtasks.

### Phase 2: ACP Integration & Skill System (Week 5-6)

**Goal:** Agents can use external agents (Hermes, Opencode, Codex) for tasks.

**Tasks:**
1. Implement ACP bridge — spawn external agents via ACP protocol
2. Implement skill registry — discover, load, and distribute skills
3. Implement tool distribution — each agent type gets its tools
4. Implement memory system — lessons learned, cross-session persistence
5. Implement project memory — concise summary of what happened, what was learned

### Phase 3: Reliability & Scale (Week 7-8)

**Goal:** Make the system robust and handle complex projects.

**Tasks:**
1.  Implement hung task detection — timeout-based + anomaly detection
2.  Implement task respawn logic — kill and retry with reformulated specs
3.  Implement escalation UI — show escalated issues prominently in all PM tools
4.  Implement project export — save project state for later resumption
5.  ~~Implement "Project Memory"~~ — REMOVED: Workers own their own memory. CelloS only tracks project state.
6.  Implement multi-project support — run multiple CelloS in parallel
7.  Implement **Budget Prediction** — Conductor estimates total cost before execution
8.  Implement **Cost Tracking** — Aggregate token usage from workers into a project "bill"
9.  Implement **Review Agent** — Automated post-mortem generation at the end of projects

### Phase 4: Polish & Distribution (Week 9-10)

**Goal:** Make it easy to install and use.

**Tasks:**
1.  Implement `cellos init` — scaffolds a new project
2.  Implement `cellos status` — shows current project state
3.  Implement `cellos deploy` — one-command deployment
4.  Write documentation — getting started, architecture, contributing
5.  Create example projects — demonstrate the framework
6.  Publish to PyPI — `pip install cellos`
7.  Create Docker image — `docker run cellos`

---

## 8. NEXT STEPS — Immediate Actions

1.  **Create the project repo** — `cellos` on GitHub
2.  **Phase 0 scaffold** — Use Opencode to create the initial project structure
3.  **Implement Task + Plan models** — These are the data foundation
4.  **Implement the Conductor** — The most critical piece. Test it thoroughly.
5.  **Build the PM adapters** — Get at least one integration working early (Trello or Jira are good starting points)
6.  **Iterate** — Each phase builds on the last. Don't rush.

### Recommended Development Approach

-  **Use Opencode as your primary coding agent** — It's good at structured implementation
-  **Use VSCode for code review and navigation** — Your eyes on the code
-  **Use Hermes for research and planning** — Ask it to review designs, suggest improvements
-  **Use Codex for complex implementation** — When Opencode needs help with a tricky piece
-  **Write tests as you go** — Especially for the orchestration logic (task resolution, escalation, loop detection)
-  **Document as you build** — Each phase should update this document

### Development Principles

1.  **Start with the Conductor** — If planning doesn't work, nothing else matters
2.  **Get the Trello adapter working early** — You need to see the plan in a real PM tool
3.  **Test with real projects** — Don't just unit test. Run actual project plans.
4.  **Keep it simple** — The power is in the hierarchy, not in features. Resist feature creep.
5.  **Make it installable** — `pip install cellos` should work from day one. No Docker-first mentality.

---

*Document created: 2026-04-22*
*Status: Brainstorm / Planning Phase*
*Next: Phase 0 implementation*
