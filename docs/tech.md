# CelloS — Technology Stack & Architecture

---

## 3. TECHNOLOGY STACK — What to Use

### Core Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Language** | Python 3.11+ | Your strength, asyncio, LLM ecosystem |
| **Async Runtime** | asyncio + httpx | Native Python async, non-blocking API calls |
| **Agent Framework** | Custom (via ACP) | Hierarchical orchestration via spawned worker agents |
| **Task Execution** | ACP spawn (Hermes/Opencode) | Workers execute tasks; CelloS orchestrates |
| **Task Queue** | Redis + Celery | Deferred to Phase 2+ |
| **State Store** | SQLite (via aiosqlite) | CelloS is source of truth; async non-blocking |

### Data Architecture

**CelloS is the Source of Truth.** All project state (plans, tasks, status, logs) lives in CelloS's SQLite database.

PM tools (Trello, Jira, Azure DevOps, and others) are **adapters** — they display data and capture user input, but they don't control logic. This ensures:

- CelloS controls orchestration (escalation, loops, dependencies)
- Not limited by PM tool features
- Each adapter is simple — just async view
- New PM tools can be added without changing core logic
| **Config** | JSON + pydantic-settings | Standard format, built-in json module, config validation |

### Configuration & Profiles (The "Magic" Layer)

| Component | Technology | Why |
|-----------|-----------|-----|
| **Global Config** | `cellos.json` | Conductor model, PM tokens, default profiles |
| **Worker Profiles** | **Hermes/Opencode Profiles** | Don't reinvent SOUL.md. The workers already have personality and memory. CelloS just references them by name. |
| **Config UI** | FastAPI + HTMX (or simple React) | A lightweight dashboard for editing `cellos.json` and viewing worker profiles. **Not** for managing tasks. |
| **ACP Bridge** | ACP protocol (Hermes/Opencode compatible) | Let users run tasks via their preferred agent. |
| **Project Memory** | SQLite | Stores project state, plans, tasks, and post-mortems as structured text. No vectorization. |

### Cost & Budgeting

| Component | Technology | Why |
|-----------|-----------|-----|
| **Cost Tracking** | **Hermes/OpenClaw Report** | Workers report token usage per task. CelloS aggregates this into a project "bill." |
| **Budget Prediction** | **Conductor (LLM)** | Before execution, the Conductor estimates the total cost based on task complexity and model pricing. |
| **Budget Alerts** | **PM Heartbeat** | If a project exceeds its budget, the PM alerts the user or pauses execution. |

### Project Management / Display

| Component | Technology | Why |
|-----------|-----------|-----|
| **Primary Interface** | **Trello / MS Teams / Notion / Jira / Azure DevOps / OpenProject / Asana** | The UI *is* the PM tool. No custom UI needed. CelloS pushes plans and tasks back to the user's existing tool. |
| **Trello Integration** | Trello API (webhook + data sync) | Users see the plan as a new list, tasks as cards. They approve by moving cards to "Approved". |
| **MS Teams Integration** | Teams Bot + Adaptive Cards | Users get a "Plan for Review" card in chat. They click "Approve" or "Edit". |
| **Notion Integration** | Notion API | Users see the plan as a database view. |
| **Jira Integration** | Jira REST API + webhooks | Issues, sprints, boards. Enterprise-friendly. |
| **Azure DevOps Integration** | Azure DevOps REST API | Work items, pipelines, approvals. |
| **OpenProject Integration** | OpenProject API | Open source alternative to Jira. |
| **Asana Integration** | Asana API | Projects, tasks, timelines. |
| **Status Cards** | Custom JSON schema | Machine-readable status for PM heartbeat. |

### ACP / Agent Communication Protocol

| Component | Technology | Why |
|-----------|-----------|-----|
| **ACP Bridge** | ACP protocol (Hermes/Opencode compatible) | Let users run tasks via their preferred agent |
| **Task Specs** | JSON schema | Standard, machine-parseable task definitions |
| **Skill Registry** | File-based (SKILL.md + tools/) | Like Hermes, but CelloS-specific |
| **Tool Distribution** | Pip packages + file-based | Easy to install, easy to share |

### Agent Types & Model Recommendations

| Agent | Recommended Models | Reasoning |
|-------|-------------------|-----------|
| **Conductor** | **Claude Opus, GPT-4.5, or equivalent** | **CRITICAL:** The Conductor needs the highest reasoning ability to abstract vague requests into structured plans. If the Conductor is dumb, the plan is garbage. |
| **Architects** | Claude Sonnet, GPT-4o, or Qwen 32B | Good at technical decisions, but can be a smaller model than the Conductor. |
| **Engineers** | Qwen 9B, DeepSeek 7B, or Llama 3 8B | Task-specific, small enough for local. They execute the plan, they don't make the plan. |
| **Test Engineers** | Qwen 9B or DeepSeek 7B | Pattern matching, good at finding bugs. |
| **PM Heartbeat** | Rule-based (no LLM) | Simple status checks, no heavy reasoning needed. |

### Skills / Tools System

```
cellos/
├── skills/
│   ├── python-engineer/
│   │   ├── SKILL.md
│   │   ├── tools/
│   │   │   ├── setup_env.py
│   │   │   ├── write_code.py
│   │   │   └── run_tests.py
│   │   └── templates/
│   ├── web-engineer/
│   ├── devops-engineer/
│   └── test-engineer/
├── models/
│   ├── conductor.json    # Model config for Conductor
│   ├── architect.json    # Model config for Architects
│   └── engineer.json     # Model config for Engineers
└── configs/
    └── default.json      # Global defaults
```

### Key Dependencies (Python)

```
aiosqlite>=0.20        # Async SQLite
httpx>=0.27            # Async HTTP client (PM adapters)
rich>=13.0             # CLI display
pydantic>=2.0          # Config validation
click>=8.0             # CLI framework
```

---

## 3.5 CONFIGURATION & PROFILES — The "Magic" Layer

You asked the right question: **Where do we put the personality (SOUL.md) and system prompts?**

**Answer: In the workers (Hermes/Opencode), not in CelloS.**

### Why CelloS Shouldn't Manage Worker Personalities

If CelloS injects prompts at runtime and bypasses Hermes, you lose:
*   **SOUL.md:** The agent's personality and behavioral guidelines.
*   **Persistent Memory:** The agent's history and user profile.
*   **Tool Ecosystem:** The agent's ability to use the terminal, browser, and other tools.
*   **The "Magic":** The reason Hermes/Opencode are powerful in the first place.

### The Solution: Profiles + ACP Bridge

CelloS manages the **assignment** of workers, not their **personality**.

1.  **CelloS's Job:** "I need a Python Engineer. I have a Python profile in Hermes called 'dev-python'. I will spawn Hermes via ACP and say: 'Load profile dev-python and execute this task.'"
2.  **Hermes's Job:** "Okay, I have loaded the 'dev-python' profile. Here is my system prompt, my memory, and my tools. I will execute the task."

### Configuration Structure

```
cellos/
├── cellos.json              # Global CelloS config (Conductor model, PM tokens)
├── profiles/               # CelloS-managed profiles (references to Hermes/Opencode)
│   ├── python-engineer.json
│   ├── web-engineer.json
│   └── devops-engineer.json
├── configs/                # Worker-specific configs (injected into the worker)
│   ├── python-engineer/
│   │   ├── system_prompt.md  # The "SOUL.md" for this role
│   │   └── skills/           # Skills specific to this role
│   └── web-engineer/
└── models/                 # Model routing config
    ├── conductor.json
    ├── architect.json
    └── engineer.json
```

### How It Works in Practice

1.  **User edits `cellos.json`** via the Config Dashboard or CLI.
2.  **User edits `profiles/python-engineer.json`** to point to a Hermes profile or inject a custom system prompt.
3.  **CelloS spawns the worker** via ACP, passing the profile name.
4.  **Worker loads its profile** (SOUL.md, memory, tools) and executes the task.

### Config Dashboard

A lightweight web dashboard (FastAPI + HTMX) for:
*   Editing `cellos.json` (global settings).
*   Viewing and editing worker profiles (system prompts, SOUL.md).
*   Assigning models to roles.
*   Viewing logs and task history.
*   **Viewing the "Bill"** — Real-time cost tracking per project.

**This is NOT the execution UI.** It's the "Settings" page for the orchestration engine. The execution UI is Trello/Teams/Notion.

### Budget Prediction & Tracking

**How it works:**
1.  **Pre-flight Estimate:** When the Conductor generates a plan, it also generates a **Budget Estimate**. It looks at the complexity of each task, the models required, and the current pricing of those models to give a total predicted cost. "This project will cost ~$15."
2.  **Real-time Tracking:** As workers execute tasks, they report token usage (via Hermes/OpenClaw). CelloS aggregates this into a running total. "Project is at $4.50 of $15.00."
3.  **Budget Alerts:** If a project exceeds its budget, the PM Heartbeat can alert the user in Trello/Teams or pause execution.

---

## 5. HIGH-LEVEL ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────┐
│                    PM TOOLS (The Interface)                     │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │
│  │  Trello  │  │ MS Teams │  │  Notion  │                     │
│  │  (Board) │  │ (Bot)    │  │  (DB)    │                     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                     │
│       │              │              │                           │
│       └──────────────┼──────────────┘                           │
│                      │                                          │
└──────────────────────┼──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                        CELLOS (The OS)                          │
│                                                                 │
│  ┌───────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │  Conductor│    │   Kanban     │    │   Task Queue    │    │
│  │ (Planner) │←──→│   Board      │←──→│   (Plans, Tasks) │    │
│  │(Claude    │    └──────────────┘    └──────────────────┘    │
│  │ Opus)     │                                                 │
│  └──────┬────┘                                                 │
│         │                                                      │
│              ┌────────────▼────────────┐                        │
│              │    APPROVAL GATE        │                        │
│              │   (Plan → User → OK)    │                        │
│              └────────────┬────────────┘                        │
│                           │                                     │
│         ┌─────────────────┼─────────────────┐                  │
│         │                 │                 │                  │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐           │
│  │  Architect  │  │  Architect  │  │  Architect  │           │
│  │  (Backend)  │  │  (Frontend) │  │  (DevOps)   │           │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘           │
│         │                 │                 │                  │
│         │    ┌────────────▼────────────┐    │                  │
│         │    │   APPROVAL GATE (Arch)  │    │                  │
│         │    └────────────┬────────────┘    │                  │
│         │                 │                 │                  │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐           │
│  │  Engineer   │  │  Engineer   │  │  Engineer   │           │
│  │  (Python)   │  │  (JS/TS)    │  │  (DB/infra) │           │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘           │
│         │                 │                 │                  │
│         │    ┌────────────▼────────────┐    │                  │
│         │    │   TEST ENGINEERS        │    │                  │
│         │    └────────────┬────────────┘    │                  │
│         │                 │                 │                  │
│         │    ┌────────────▼────────────┐    │                  │
│         │    │   PM HEARTBEAT          │    │                  │
│         │    │   (Monitor/Prod/Kill)   │    │                  │
│         │    └─────────────────────────┘    │                  │
│         │                                   │                  │
│         │    ┌─────────────────────────┐    │                  │
│         │    │   COST TRACKER          │    │                  │
│         │    │   (Budget/Usage)        │    │                  │
│         │    └─────────────────────────┘    │                  │
│         │                                   │                  │
│         │    ┌─────────────────────────┐    │                  │
│         │    │   ESCALATION CHAIN      │    │                  │
│         │    │   (Fail Up, Not Loop)   │    │                  │
│         │    └─────────────────────────┘    │                  │
│         │                                   │                  │
│         │    ┌─────────────────────────┐    │                  │
│         │    │   DECISION LOOP         │    │                  │
│         │    │   (Decompose/Re-plan/   │    │                  │
│         │    │    Switch/Escalate)     │    │                  │
│         │    └─────────────────────────┘    │                  │
│         │                                   │                  │
│         │    ┌─────────────────────────┐    │                  │
│         │    │   REVIEW & LESSONS      │    │                  │
│         │    │   (Post-Mortem)         │    │                  │
│         │    └─────────────────────────┘    │                  │
│         │                                   │                  │
│         │    ┌─────────────────────────┐    │                  │
│         │    │   ACP BRIDGE            │    │                  │
│         │    │   (Hermes/Opencode/     │    │                  │
│         │    │    Codex integration)    │    │                  │
│         │    └─────────────────────────┘    │                  │
│         │                                   │                  │
│         │    ┌─────────────────────────┐    │                  │
│         │    │   TRELLO SYNC           │    │                  │
│         │    │   (Kanban ↔ Trello)     │    │                  │
│         │    └─────────────────────────┘    │                  │
│         └───────────────────────────────────┘                  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  TASK QUEUE (Redis) — Tasks, Dependencies, Status      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Task Schema (JSON)

```json
{
  "task": {
    "id": "eng-001",
    "type": "engineer",
    "agent_type": "python-engineer",
    "model": "qwen/qwen3.6-35b",
    "status": "pending",
    "title": "Setup FastAPI project structure",
    "description": "Create the initial FastAPI project with...",
    "dependencies": ["arch-001"],
    "approval_required": true,
    "max_retries": 3,
    "retry_count": 0,
    ...
  }
}
```

### Plan Schema (JSON)

```json
{
  "plan": {
    "version": 1,
    "title": "Build a FastAPI CRUD API",
    "created_by": "conductor",
    "status": "pending_approval",
    "goals": ["Build a REST API", "Include JWT auth", "Deploy to cloud"],
    "phases": [
      {
        "name": "Implementation",
        "status": "pending",
        "approval_required": true,
        "tasks": [
          {
            "ref": "eng-001",
            "type": "engineer",
            "title": "Setup FastAPI project",
            "depends_on": ["arch-001"]
          }
        ],
        "depends_on": ["arch-001", "arch-002"]
      }
    ],
    "hard_constraints": ["Must include type hints", "Must have 80%+ test coverage"],
    "questions_for_user": ["Which cloud provider: AWS, GCP, or Azure?"]
  }
}
```
