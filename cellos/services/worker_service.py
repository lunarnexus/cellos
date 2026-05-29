"""WorkerService — build connector → build prompt → run task → save result.

Orchestrates a single worker execution: resolves the agent from config, builds
the appropriate connector, assembles the prompt via profile-driven builder, runs
the agent, and persists results through planning or execution services. Tracks
attempts with start→run→complete lifecycle. Logs to project directory.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any

from cellos.config import AgentCatalogEntry, CellosConfig
from cellos.connectors.base import ConnectorResult, TaskConnector
from cellos.db import CellosDatabase
from cellos.models import AttentionReason, Task, TaskStatus
from cellos.prompt_builder import build_task_prompt

logger = logging.getLogger(__name__)


class WorkerError(Exception):
    """Raised when a worker fails to execute."""


def resolve_agent(config: CellosConfig, task: Task) -> AgentCatalogEntry:
    """Resolve the agent for a task.

    Resolution order:
      1. task.agent_id (explicit override)
      2. task.role (default mapping)
      3. config.agents.default_agent_id (global default)

    Args:
        config: Loaded CellosConfig with agent catalog.
        task: The task needing an agent.

    Returns:
        Resolved AgentCatalogEntry.

    Raises:
        WorkerError: If no agent can be resolved.
    """
    agent = None
    if task.agent_id:
        agent = config.get_agent(task.agent_id)
    if not agent:
        agent = config.get_agent(task.role.value)
    if not agent:
        agent = config.get_agent()
    if agent is None:
        raise WorkerError(
            f"No agent configured for task {task.id} "
            f"(agent_id={task.agent_id}, role={task.role.value}, "
            f"default={config.agents.default_agent_id})"
        )
    return agent


def _build_connector(agent: AgentCatalogEntry, timeout_seconds: int) -> TaskConnector:
    """Build a connector from agent catalog entry.

    Args:
        agent: Resolved agent config from the registry/catalog.
        timeout_seconds: Timeout for the connector execution.

    Returns:
        A configured TaskConnector instance.

    Raises:
        WorkerError: If the connector type is unknown or fails to initialize.
    """
    if agent.connector == "fake_acp":
        from cellos.connectors.fake_acp import FakeAcpConnector

        return FakeAcpConnector(options=agent.options)

    if agent.connector == "cellos_acp":
        try:
            from cellos.connectors.cellos_acp import CellosAcpConnector
        except ImportError as e:
            raise WorkerError(f"Failed to import cellos-acp connector: {e}") from e

        options = dict(agent.options or {})
        options.setdefault("timeout_seconds", timeout_seconds)
        if "log_file" not in options:
            debug_log = os.environ.get("CELLOS_DEBUG_LOG")
            if debug_log:
                options["log_file"] = debug_log
        return CellosAcpConnector(options=options)

    raise WorkerError(f"Unknown connector type: {agent.connector}")


def _build_failure_summary(diagnostics: dict[str, Any] | None) -> str:
    """Build a diagnostic-aware failure summary string.

    Uses factual descriptions based on available diagnostic data.
    """
    if not diagnostics:
        return "No output from agent"

    parts: list[str] = []

    if diagnostics.get("timeout"):
        parts.append("Agent timed out")
    elif diagnostics.get("aborted"):
        parts.append("Agent aborted")
    elif diagnostics.get("error_type"):
        parts.append(f"Agent error: {diagnostics['error_type']}")
    else:
        parts.append("Agent failed")

    tool_name = diagnostics.get("active_tool_name")
    if tool_name:
        parts[-1] += f" while tool `{tool_name}` was running"

    nested = diagnostics.get("nested_session_id")
    if nested:
        parts.append(f"Nested session: {nested}")

    last_event = diagnostics.get("last_event_type")
    last_at = diagnostics.get("last_event_at")
    if last_event:
        event_desc = f"Last event: {last_event}"
        if last_at:
            event_desc += f" at {last_at}"
        parts.append(event_desc)

    partial_text = diagnostics.get("partial_text") or diagnostics.get("last_message_preview", "")
    if partial_text and len(partial_text) > 10:
        parts.append(f"Partial output: {partial_text[:120]}")

    return ". ".join(parts)


async def run_task_worker(
    db: CellosDatabase,
    task_id: str,
    mode: str,  # "planning" or "execution"
    config: CellosConfig,
    workdir: str | None = None,
) -> Task:
    """Execute a single worker run for the given task.

    Full lifecycle:
      1. Load task from DB
      2. Transition to IN_PROGRESS (prevents double-scheduling)
      3. Create attempt record
      4. Resolve agent → build connector
      5. Build prompt from profiles + task context
      6. Run connector
      7. Save result via planning/execution service
      8. Complete attempt with diagnostics

    Args:
        db: Connected database facade.
        task_id: ID of the task to execute.
        mode: "planning" or "execution".
        config: Loaded CellosConfig with agent catalog and prompt profiles.
        workdir: Optional working directory for subprocess connectors.

    Returns:
        Updated Task after execution.

    Raises:
        WorkerError: If any step fails (task not found, connector error, etc.).
    """
    # 1. Load task
    task = await db.get_task(task_id)
    if task is None:
        raise WorkerError(f"Task {task_id} not found")

    logger.info("Worker starting for task %s mode=%s", task.id, mode)

    attempt = None
    diagnostics: dict[str, Any] | None = None

    try:
        # 2. Transition to IN_PROGRESS (prevents double-scheduling by scheduler)
        if mode == "planning":
            allowed = [TaskStatus.DRAFT]
        else:
            allowed = [TaskStatus.APPROVED]

        if task.status not in allowed:
            raise WorkerError(
                f"Cannot {mode} task {task_id}: status is '{task.status.value}', expected one of {[s.value for s in allowed]}"
            )

        updated_task = task.model_copy(update={
            "status": TaskStatus.IN_PROGRESS,
            "updated_at": datetime.datetime.now(),
        })
        await db.update_task(updated_task)
        logger.info("Task %s transitioned to IN_PROGRESS", task_id)

        # 3. Resolve agent: task.agent_id → task.role → config default
        agent = resolve_agent(config, task)

        # Find the agent's key in the catalog (for attempt tracking)
        agent_key = next(
            (k for k, v in config.agent_catalog.items() if v is agent),
            agent.connector,
        )

        attempt = await db.create_attempt(
            task_id=task_id, mode=mode, agent_id=agent_key
        )
        logger.info("Attempt %s created for task %s", attempt.id, task_id)

        # 4. Build connector from agent config
        timeout = config.worker.timeout_seconds
        connector: TaskConnector = _build_connector(agent, timeout)

        # 5. Build prompt from profiles + task context
        if mode == "planning":
            comments = await db.list_comments(task_id)
            comment_text_parts: list[str] = []
            for c in comments:
                label = f"[{c.author_type.value}] {c.content}"
                comment_text_parts.append(label)

            task_dict = _task_to_prompt_dict(task, extra={
                "comments": "\n".join(comment_text_parts) if comment_text_parts else None,
            })
        else:
            # Execution mode — no comments in prompt (plan is authoritative context)
            task_dict = _task_to_prompt_dict(task)

        prompt_text = build_task_prompt(
            task=task_dict,
            profiles=config.prompt_profiles,
            mode=mode,
            plan=task.plan if mode == "execution" else None,
        )

        # 6. Run connector — now returns ConnectorResult
        logger.info("Running connector for task %s (timeout=%ds)", task_id, timeout)
        logger.debug("Prompt for task %s mode=%s:\n%s", task_id, mode, prompt_text)
        conn_result: ConnectorResult = await asyncio.wait_for(
            connector.run_task(task=updated_task or task, workdir=workdir, mode=mode, prompt_text=prompt_text),
            timeout=timeout + 10,  # Small buffer for async overhead
        )

        result = conn_result.task_result
        diagnostics = conn_result.diagnostics
        logger.info("Connector returned: success=%s summary=%s", result.success, result.summary[:200])

        # 7. Save result via appropriate service
        if mode == "planning":
            from cellos.services.planning_service import save_planning_result

            plan_text = result.output or result.summary
            await save_planning_result(db, task_id, plan_text=plan_text, success=result.success)
        else:
            created_child_ids: list[str] = []

            # Create planned child tasks only after the parent plan is approved
            # and the parent task enters execution.
            current_task = await db.get_task(task_id)
            if current_task and current_task.prompt_text:
                from cellos.structured_response import (
                    child_tasks_from_response,
                    parse_planning_response,
                )

                planned = parse_planning_response(current_task.prompt_text)
                if result.success and planned and planned.child_tasks:
                    from cellos.services.task_service import TaskService as TSvc

                    children_data = child_tasks_from_response(planned, task_id)
                    tservice = TSvc(db)
                    for child_data in children_data:
                        child = await tservice.create_task(**child_data)  # type: ignore[arg-type]
                        created_child_ids.append(child.id)
                        logger.info("Child task %s created from execution of %s", child.id, task_id)

            action_output = result.output or ""
            if action_output.strip():
                from cellos.task_actions import parse_create_task_actions, tasks_from_create_actions

                parsed_actions = parse_create_task_actions(action_output)
                children_data = tasks_from_create_actions(
                    parent_id=task_id, actions=parsed_actions,
                    preapprove_research_tasks=config.approvals.preapprove_research_tasks,
                )

                from cellos.services.task_service import TaskService as TSvc
                tservice = TSvc(db)
                for child_data in children_data:
                    child = await tservice.create_task(**child_data)  # type: ignore[arg-type]
                    created_child_ids.append(child.id)
                    logger.info("Child task %s created from execution of %s", child.id, task_id)

            if created_child_ids:
                from cellos.models import TaskDependency

                await db.add_dependencies(
                    task_id,
                    [TaskDependency(task_id=child_id) for child_id in created_child_ids],
                )

            from cellos.services.execution_service import save_execution_result
            exec_result = await save_execution_result(
                db,
                task_id,
                action_output or result.summary,
                success=result.success,
                wait_for_children=bool(created_child_ids),
            )

        # 8. Complete attempt with diagnostics
        final_task = await db.get_task(task_id)
        if final_task:
            status_to_use = TaskStatus.DONE if result.success else TaskStatus.FAILED
            if mode == "planning":
                summary = _build_failure_summary(diagnostics) if not result.success else result.summary[:500]
                await db.update_attempt(
                    attempt.id, status_to_use, result_summary=summary, diagnostics=diagnostics
                )
            else:
                summary = _build_failure_summary(diagnostics) if not result.success else exec_result.summary[:500]
                await db.update_attempt(
                    attempt.id, status_to_use,
                    result_summary=summary,
                    diagnostics=diagnostics
                )

        logger.info("Worker completed for task %s", task_id)
        return final_task or updated_task

    except Exception as e:
        # On failure: mark attempt failed with diagnostics, transition task back
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("Worker failed for task %s mode=%s: %s", task_id, mode, error_msg)

        if attempt is not None:
            try:
                # Enhance diagnostics with error info
                fail_diagnostics = dict(diagnostics or {})
                fail_diagnostics.setdefault("error_type", type(e).__name__)
                fail_diagnostics.setdefault("error_message", str(e)[:500])
                await db.update_attempt(
                    attempt.id, TaskStatus.FAILED,
                    error_message=error_msg[:500],
                    diagnostics=fail_diagnostics,
                )
            except Exception:
                logger.error("Failed to update attempt %s on error", getattr(attempt, "id", "?"))

        # Restore task status based on mode
        current = await db.get_task(task_id)
        if current:
            restore_status = (
                TaskStatus.DRAFT if mode == "planning" else TaskStatus.APPROVED
            )
            restored = current.model_copy(update={
                "status": restore_status,
                "updated_at": datetime.datetime.now(),
            })
            # Set attention so the scheduler surfaces the failure for review
            restored = restored.requires_attention(
                AttentionReason.EXECUTION_FAILED,
                detail=f"Worker {mode} failed: {error_msg[:120]}",
            )
            await db.update_task(restored)

        raise WorkerError(f"Worker failed for task {task_id} mode={mode}: {error_msg}") from e


def _task_to_prompt_dict(task: Task, extra: dict | None = None) -> dict[str, object]:
    """Convert a Task model to the dict format expected by build_task_prompt().

    Args:
        task: The domain Task instance.
        extra: Optional additional keys to merge into the result (e.g., comments).

    Returns:
        Dict with prompt_builder-compatible keys.
    """
    result = {
        "role": str(task.role) if task.role else "",
        "title": task.title or "",
        "status": str(task.status),
        "task_type": str(task.task_type) if task.task_type else "",
        "details": task.details or "",
        "success_criteria": task.success_criteria,
        "failure_criteria": task.failure_criteria,
    }

    # Remove empty values for cleaner prompt output
    result = {k: v for k, v in result.items() if v}

    if extra:
        result.update(extra)

    return result


__all__ = ["run_task_worker", "_build_connector", "resolve_agent", "WorkerError", "_build_failure_summary"]
