# Project Charter: CelloS (AI Orchestration Framework)

## 1. Project Overview
*   **Project Name:** CelloS
*   **Vision:** *"The power of an orchestra is not in any single instrument, but in how they work together."*
*   **Mission:** To provide a reliable, hierarchical AI orchestration layer that manages multi-agent projects through existing project management tools (Trello, Teams, Notion, Jira, Azure DevOps, OpenProject, Asana), optimizing for cost, reliability, and human oversight.

## 2. Problem Statement
Current AI orchestration solutions (CrewAI, LangGraph, AutoGen) suffer from:
1.  **Flat Hierarchy:** Agents are peers; no natural "Manager → Worker" structure.
2.  **Code-Heavy:** Require writing graph definitions in code, not natural language.
3.  **No Human Oversight:** Lack approval gates, escalation chains, and PM integration.
4.  **Context Bloat:** Accumulate too much context, leading to hallucinations and high costs.
5.  **Single-Agent Focus:** (e.g., OpenDevin) or rigid pipelines (e.g., CrewAI).
6.  **AI Limitations & Security:** Small models are easily overwhelmed by complexity. Without strict task decomposition into manageable chunks and human oversight for security/validation, they hallucinate or produce unsafe code. Current frameworks lack these critical guardrails.

## 3. Proposed Solution
CelloS is the **OS** for AI agents. It is a lightweight orchestration engine that:
*   Uses a **Conductor** (smart LLM) to plan projects from vague requests.
*   Decomposes plans into hierarchical tasks (Architects → Engineers).
*   Routes tasks to existing agents (Hermes, Opencode, Codex) via an **ACP Bridge**.
*   Syncs status to **Trello/Teams/Notion/Jira/Azure DevOps/OpenProject/Asana** for human oversight.
*   Tracks costs and learns lessons for continuous improvement.

## 4. Scope

### In Scope (MVP)
*   **Core Engine:** Task/Plan models, Conductor logic, Escalation/Loop detection.
*   **ACP Bridge:** Integration with Hermes and Opencode.
*   **PM Adapters:** Trello, MS Teams, Notion, Jira, Azure DevOps, OpenProject, Asana integration (read/write/approval).
*   **Cost Tracking:** Real-time token aggregation and budget alerts.
*   **CLI:** `cellos init`, `cellos run`, `cellos status`.

### Out of Scope (MVP)
*   Building a new agent (we integrate existing ones).
*   Custom UI for execution (we use Trello/Teams).
*   Jira/Linear/Asana support (Post-MVP).
*   Multi-project coordination (Post-MVP).

## 5. Key Deliverables
1.  **CelloS Package:** `pip install cellos`
2.  **Conductor Agent:** Generates structured plans from natural language.
3.  **Task Queue:** Redis-based dependency resolution.
4.  **Trello/Teams Adapters:** Two-way sync of plans and status.
5.  **Documentation:** Getting started guide, architecture docs.

## 6. Success Criteria
*   **Plan Generation:** Conductor produces a valid, decomposable plan from a vague prompt.
*   **Worker Execution:** A Hermes/Opencode agent successfully executes a task via ACP.
*   **PM Sync:** Plan appears in Trello; user approval updates engine state.
*   **Cost Tracking:** Project bill accurately reflects token usage.
*   **Reliability:** Loop detection prevents infinite retry cycles.

## 7. Timeline & Milestones (10 Weeks)
*   **Phase 0 (Week 1-2):** Core Engine (Conductor, Task/Plan models).
*   **Phase 1 (Week 3-4):** PM Adapters (Trello/Teams/Notion/Jira/Azure DevOps/OpenProject/Asana).
*   **Phase 2 (Week 5-6):** ACP Integration & Skills.
*   **Phase 3 (Week 7-8):** Reliability & Scale (Escalation, Cost, Lessons).
*   **Phase 4 (Week 9-10):** Polish & Distribution (CLI, Docs, PyPI).

## 8. Key Risks & Mitigations
*   **Risk:** Conductor prompt instability (hallucinates invalid plans).
    *   *Mitigation:* Strict JSON schema validation; iterative prompt tuning; fallback to manual plan editing.
*   **Risk:** ACP protocol complexity.
    *   *Mitigation:* Start with a simple JSON-over-stdin/stdout protocol; expand later.
*   **Risk:** LLM costs spiraling.
    *   *Mitigation:* Model tiering (small models for execution); budget caps; real-time tracking.
*   **Risk:** Trello/Teams API rate limits.
    *   *Mitigation:* Caching; batched updates; webhook optimization.

## 9. Stakeholders
*   **Project Sponsor:** [User]
*   **Lead Architect:** [User/Agent]
*   **Target Users:** Developers and technical PMs managing AI projects.
