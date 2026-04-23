# CELLO — Strategy & Vision

> "The power of an orchestra is not in any single instrument, but in how they work together."

---

## 1. COMPETITIVE LANDSCAPE — What Exists Today
# CelloS — Strategy & Vision

> "The power of an orchestra is not in any single instrument, but in how they work together."

---

## 1. COMPETITIVE LANDSCAPE — What Exists Today

### Major Players

#### CrewAI (crewai.com)
- **Strengths:** Role-based agent design (Researcher, Writer, Reviewer), easy task delegation, well-documented, large community. Good for linear pipelines.
- **Weaknesses:** Rigid agent lifecycle (agents persist too long), no hierarchical escalation, limited error recovery, no kanban/project management UI, context bloat when agents accumulate.
- **Gap:** No natural hierarchy. All agents are peers. No "escalation up the food chain."

#### LangGraph (langchain.github.io/langgraph)
- **Strengths:** Graph-based orchestration (cycles, conditionals, branching), fine-grained control over agent flow, production-grade, integrates with entire LangChain ecosystem.
- **Weaknesses:** Steep learning curve, requires writing graph definitions in code (not natural language), no built-in project management, no user approval gates, no visual dashboard.
- **Gap:** Too developer-centric. Not accessible to non-coders. No "Conductor" concept.

#### Microsoft AutoGen (autogen.ai)
- **Strengths:** Multi-agent conversation patterns, code execution sandbox, group chat mode, enterprise backing.
- **Weaknesses:** Complex setup, heavy resource usage, limited error recovery, no hierarchical structure, no project management integration.
- **Gap:** No natural task decomposition. No approval gates. No small-model optimization.

#### OpenDevin / OpenHands
- **Strengths:** Autonomous coding, browser use, file system access, good for single-agent coding tasks.
- **Weaknesses:** Single-agent focused (no orchestration), context bloat, no team coordination, no PM features.
- **Gap:** No multi-agent orchestration at all.

#### Dify.ai
- **Strengths:** Visual workflow builder, AI app deployment, good UI, large feature set.
- **Weaknesses:** More of an AI app platform than an orchestration framework. Agents are secondary. No hierarchical delegation. Limited customization.
- **Gap:** Not designed for agent-to-agent orchestration.

#### Semantic Kernel (Microsoft)
- **Strengths:** SDK for embedding AI into apps, plugin system, multi-provider support.
- **Weaknesses:** SDK-level, not an application framework. No orchestration UI, no PM features.
- **Gap:** Infrastructure layer, not orchestration layer.

#### AutoGPT / BabyAGI (Legacy)
- **Strengths:** Pioneered autonomous agents, task queues, goal pursuit.
- **Weaknesses:** Unreliable, context bloat, no structure, no human oversight, no escalation.
- **Gap:** These are what CelloS should be — structured, reliable, human-in-the-loop.

#### OpenClaw (mentioned by user)
- **Strengths:** Pre-made skills, easy setup, "anyone can use it" philosophy, good skill ecosystem.
- **Weaknesses:** Single-agent focused, no orchestration, no hierarchy, no PM integration.
- **Gap:** This is CelloS's distribution advantage — but CelloS adds orchestration on top.

#### Hermes Agent (your existing project)
- **Strengths:** Multi-platform, skills system, memory, MCP, provider-agnostic.
- **Weaknesses:** Single-agent paradigm. No orchestration between agents.

#### Opencode (mentioned by user)
- **Strengths:** IDE-integrated, good coding agent.
- **Weaknesses:** Single-agent, no orchestration.

### Industry Gaps — Where CelloS Can Win

1.  **Hierarchical task decomposition** — Nobody does the Conductor → Architects → Engineers model well. CrewAI is flat. LangGraph requires code graphs.
2.  **Small-model optimization** — The industry assumes GPT-4/Claude for everything. Your insight (break tasks down so 9B models work) is underexplored. Most frameworks just throw bigger models at problems.
3.  **Human approval gates** — AutoGen and CrewAI have minimal human oversight. LangGraph has no UI. CelloS's plan-approve-execute flow is a real differentiator.
4.  **Project management integration** — Kanban boards, Trello sync, heartbeat monitoring. Nobody does this. It's the "corporate PM meets AI" angle.
5.  **Escalation chains** — Agents that can fail up the hierarchy rather than looping forever. This is basically how real teams work.
6.  **Model-per-agent specialization** — Let the Conductor use Claude Opus, engineers use Qwen 9B, researchers use cheaper models. Nobody does this well.
7.  **Reliability over autonomy** — The market is obsessed with "fully autonomous." The real value is "reliable with human oversight." Think industrial automation, not science fiction.

---

## 2. METHODOLOGY — Is Your Approach Good?

**Yes. It's excellent.** Here's why:

### The "Manager vs. Worker" Architecture

**CelloS is the Manager. Hermes, Codex, and Opencode are the Workers.**

This is the critical design decision. You do **not** want to recreate agent memory, SOUL.md, or tool use inside CelloS. Those problems are already solved by Hermes, OpenClaw, and Codex.

*   **CelloS's Job:** Orchestration, planning, project management, status tracking, escalation.
*   **Workers' Job:** Coding, browsing, memory, personality, tool use.

CelloS is the **OS**. The other agents are the **Apps**.

### Why CelloS Should Be the Top-Level Orchestrator (Not a tool inside Hermes)

1.  **Agnosticism:** If CelloS is a tool *inside* Hermes, you are locked into Hermes. You can't use Codex for the Python work and Opencode for the DevOps work. CelloS's power comes from being the **universal glue**. It picks the best tool for the job.
2.  **Scope:** Hermes is great at *being* an agent. CelloS is great at *managing* agents. These are different problems.
    *   **Hermes** handles: "How do I write this code? What tools do I need? What is my personality?"
    *   **CelloS** handles: "What needs to be built? Who should build it? Is it on track? What went wrong?"
3.  **The "Brain" Question:** You asked if CelloS needs a new brain. **Yes, but a specific kind.**
    *   CelloS needs a **Conductor (Planner)**. This is a narrow "brain" that *only* does high-level planning. It doesn't write code, browse the web, or manage files. It just looks at a vague request and outputs a structured plan.
    *   **CRITICAL:** The Conductor **must** be the smartest model available (Claude Opus, GPT-4.5). Planning is the hardest part of the system. If the Conductor is dumb, the plan is garbage, and you just get "efficiently wrong" results. It needs strong reasoning to abstract vague requests into structured plans that smaller models can execute without hallucinating.

### The Decision & Escalation Loop

This is the core of CelloS's intelligence. When an agent fails or reports a problem, the **higher-tier agent** (Architect or Conductor) receives the report. It doesn't just retry. It *decides*.

**The Four Outcomes:**
When a task fails, the higher-tier agent evaluates the failure and chooses exactly one of four paths:

1.  **Decompose (Break it down):** "This task is too complex for the current agent/model. Split it into smaller sub-tasks."
2.  **Re-plan (Rewrite the spec):** "The current approach is fundamentally flawed. The dependencies are wrong or the goal is ambiguous. Here is a new plan."
3.  **Switch Strategy (Try a different tool/model):** "The current agent/model isn't suited for this. Try a different specialist or a different LLM."
4.  **Escalate (Human intervention):** "This is a loop, a blocker, or requires judgment I don't have. The user needs to decide."

**Success Path:**
*   If the task succeeds, the PM Heartbeat updates the PM tool (Trello card to "Done", Teams card to "Approved").

**The Loop Detection Mechanism:**
*   Every task has a `resolution_history` array. If the same task is re-assigned more than N times (default 3) without success, it is automatically flagged as a **Loop** and escalated to the user. This prevents infinite retry cycles.

### Review & Lessons Learned

At the end of a project (or major phase), CelloS initiates a **Review Phase**.
*   **Who:** The Conductor (or a dedicated "Reviewer" agent).
*   **What:** "What went well? What went wrong? What should we do differently next time?"
*   **How:** The Conductor analyzes the `resolution_history`, task results, and user feedback to generate a structured **Post-Mortem**.
*   **Storage:** Lessons are stored in **Project Memory** (Vector DB) tagged by topic (e.g., "python-environment", "api-integration").
*   **Usage:** In future projects, the Conductor loads relevant lessons *before* planning. "Last time we built a FastAPI app, the database setup failed twice. This time, ensure the database driver is installed *before* the app structure."

**This is how CelloS gets smarter over time.**

---

### Borrowing vs. Building

| Feature | Who Handles It? | Why? |
|---------|----------------|------|
| **Agent Memory / SOUL.md** | **Hermes / OpenClaw** | Don't reinvent it. The workers already have this. CelloS just tells them "You are a Python engineer." |
| **Tool Use (coding, browsing)** | **Hermes / Codex** | CelloS doesn't need to know how to write code. It just assigns the task. |
| **ACP Protocol** | **CelloS** | CelloS needs to implement the ACP bridge to talk to the workers. |
| **Project Memory** | **CelloS** | CelloS needs a lightweight database for *project state* (plans, tasks, status, logs). This is not "agent memory"; it's "project history." |
| **Orchestration Logic** | **CelloS** | This is the core. The hierarchy, the approval gates, the escalation chains. |
| **PM / Kanban** | **CelloS** | The visual layer for the user to see the project status. |

### Why It Works

Your methodology maps directly to proven enterprise project management patterns:

- **Conductor = Project Manager / Product Owner** — Defines vision, creates high-level plan, gets stakeholder approval. This is PMBOK's "Define Project" phase.
- **Architects = Technical Leads** — Translate business goals into technical architecture. This is the "Architecture Design" phase in any SDLC.
- **Engineers = Developers** — Execute on detailed specs. This is "Implementation."
- **Test Engineers = QA** — Verify deliverables. This is "Testing/QA."
- **Approval Gates = Change Control Board** — User approves each phase before proceeding. This is standard enterprise governance.
- **Escalation Chain = Incident Management** — Issues propagate up when lower levels can't resolve. This is ITIL's incident escalation model.
- **Heartbeat Monitoring = Stand-up Meetings** — Periodic status checks. This is Agile's daily stand-up concept.
- **Dependency System = Critical Path Method** — Tasks have prerequisites. This is standard project management.

### Your Methodology — Refined

```
                    ┌─────────────────────┐
                    │   CONDUCTOR (User)  │
                    │   "Make me an app"  │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │   CONDUCTOR AGENT   │
                    │   (Large model)     │
                    │                     │
                    │   1. Understand     │
                    │   2. Plan           │
                    │   3. Present plan   │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │   APPROVAL GATE     │← User approves/rejects
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  ARCHITECT AGENTS   │
                    │  (Medium models)    │
                    │  - Backend Arch     │
                    │  - Frontend Arch    │
                    │  - DevOps Arch      │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │   ARCH PLAN GATE    │← User approves architecture
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │   ENGINEER AGENTS   │
                    │   (Small models)    │
                    │  - Python Eng       │
                    │  - JS Eng           │
                    │  - DB Eng           │
                    │  - etc.             │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  TEST ENGINEERS     │
                    │  (Small models)     │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │   RESULTS           │
                    └─────────────────────┘

  ┌──────────────────────────────────────────┐
  │  PROJECT MANAGER (Background Process)    │
  │  - Heartbeat pings every N minutes       │
  │  - Tracks task status                    │
  │  - Prods hung tasks                      │
  │  - Escalates failures                    │
  │  - Updates Kanban board                  │
  └──────────────────────────────────────────┘
```

### Development Methodology

CelloS will be built using a **documentation-first** approach:

1.  **Human-readable docs before code.** Every component gets its design documented in plain language first — what it does, how it fits, what the inputs/outputs are.
2.  **Code matches the docs.** The code is written to implement the documented design, not the other way around. This keeps the docs accurate and the code focused.
3.  **One file at a time.** Each task produces one artifact (a doc file or a code file). No feature is considered "done" until its doc is written and its code is complete.
4.  **Human review between phases.** Before moving from one phase to the next, the previous phase's docs and code are reviewed. This prevents compounding mistakes.
5.  **Small chunks for small models.** Every task is scoped so a 7-13B model can handle it without getting lost. If a task feels too big, break it further.

### Guiding Principles

These are the non-negotiable rules that govern every design decision in CelloS:

1.  **Execution vs. Decision** — Tasks that require minimal decision-making (boilerplate, formatting, repetitive ops) should use the smallest model possible or be handled by scripts entirely. If a task can be done deterministically, don't route it through an LLM.
2.  **Deterministic = Scripted** — Tasks that will be executed the same way every time (setup commands, file scaffolding, config generation) must be done with scripts, not LLM calls. LLM overhead is wasted here and introduces unnecessary variance.
3.  **LLMs Are Dumb — Decompose Everything** — LLMs cannot handle complex, multi-step tasks in one shot. Every task must be broken down into small enough chunks that a 7-13B model can execute it reliably. This is the core insight CelloS is built on.
4.  **LLMs Can't Be Trusted — Human Gates** — Every LLM output that touches the filesystem, runs commands, or makes architectural decisions must pass through human approval. No exceptions. This is not optional; it's the safety net that makes the whole system viable.

### Key Design Decisions

1.  **Plan-First, Execute-Second** — No agent starts working until the plan is approved. This prevents wasted compute and context.
2.  **Approval Gates at Each Phase** — User can modify plans at any stage. Cheaper to fix a plan than a bug.
3.  **Model Tiering** — Conductor: 70B+ or Claude Opus. Architects: 30-70B. Engineers: 7-13B. Tests: 7B. This optimizes cost while maintaining quality.
4.  **Bounded Error Recovery** — Agents get N rounds to self-fix, then escalate. Prevents infinite loops.
5.  **Small Context Windows** — Each agent only sees what it needs. Reduces hallucination and cost.
6.  **PM Heartbeat** — Background process monitors all active tasks. Can prod, kill, respawn, or escalate.

### Potential Pitfalls to Address

-  **Plan granularity** — If the Conductor's plan is too vague, architects fail. If too detailed, it defeats the purpose. Need a "plan schema" that forces appropriate detail.
-  **Agent communication overhead** — Every handoff costs tokens and time. Need efficient, structured communication protocols.
-  **Context accumulation** — Even with small contexts, the Conductor needs to know what happened. Need a "project memory" that's concise.
-  **Human bottleneck** — If the user is slow to approve, everything stalls. Need auto-approve defaults and async mode.
-  **Loop detection** — Agents could get stuck in retry loops. Need explicit loop detection in the PM heartbeat.

---

## 7. KEY DIFFERENTIATORS — Why CelloS Wins

1.  **Hierarchical orchestration** — Conductor → Architects → Engineers. Not flat like CrewAI, not code-graph like LangGraph.
2.  **Smart Conductor** — The planner uses the best model available (Claude Opus/GPT-4.5). It does the heavy lifting of decomposition so smaller models can succeed.
3.  **PM-First Interface** — CelloS lives inside Trello, Teams, or Notion. No custom UI to maintain. The user stays in their workflow.
4.  **Human-in-the-loop by default** — Approval gates at every phase. Auto-approve for power users.
5.  **ACP agnostic** — Don't reinvent the agent. Use Hermes, Opencode, Codex for the actual work. CelloS is the glue.
6.  **Model tiering** — Right-size the model to the task. Save money, reduce latency.
7.  **Escalation over loops** — Agents fail up, not in circles. PM detects and intervenes.
8.  **Easy to start** — `cellos init`, `cellos run`. Pre-configured skills. Like OpenClaw's "anyone can use it" philosophy but with orchestration power.
9.  **Budget Prediction & Tracking** — Know the total cost before you start. Track the bill in real-time.
10. **Continuous Improvement** — Automated "Lessons Learned" and "Post-Mortems" make CelloS smarter with every project.

---

## 9. FUTURE EXPANSION (Post-MVP)

-  **More PM integrations** — Jira, Asana, Linear, ClickUp
-  **Team mode** — Multiple Conductor agents for multi-project coordination
-  **Skill marketplace** — Users share and install skills (like Hermes skills hub)
-  **Plugin system** — Custom agent types, custom PM rules, custom integrations
-  **CI/CD pipeline** — Auto-test on PR, auto-deploy on merge
-  **Cost tracking** — Monitor LLM costs per phase, per agent
-  **Learning system** — Analyze failures, auto-improve plans and task specs
-  **Multi-orchestration** — Chain multiple CelloS together for very large projects
-  **Budget Alerts** — Auto-pause or escalate if a project exceeds its budget
-  **Cost Optimization** — Suggest cheaper models or task restructuring to reduce costs

---

*Document created: 2026-04-22*
*Status: Brainstorm / Planning Phase*
*Next: Phase 0 implementation*
