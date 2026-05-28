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
from typing import Any

from cellos.config import AgentCatalogEntry, CellosConfig
from cellos.connectors.base import TaskConnector
from cellos.db import CellosDatabase
from cellos.models import AttentionReason, Task, TaskStatus
from cellos.prompt_builder import build_task_prompt

logger = logging.getLogger(__name__)


class WorkerError(Exception):
    """Raised when a worker fails to execute."""


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
        return CellosAcpConnector(options=options)

    raise WorkerError(f"Unknown connector type: {agent.connector}")


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
      8. Complete attempt

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
        # Note: task.agent_id can be empty string (not None), so check explicitly
        agent = None
        if task.agent_id:
            agent = config.get_agent(task.agent_id)
        if not agent:
            agent = config.get_agent(task.role.value)
        if not agent:
            agent = config.get_agent()
        if agent is None:
            raise WorkerError(
                f"No agent configured for task {task_id} (agent_id={task.agent_id}, role={task.role.value}, default={config.agents.default_agent_id})"
            )

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

        # 6. Run connector
        logger.info("Running connector for task %s (timeout=%ds)", task_id, timeout)
        logger.debug("Prompt for task %s mode=%s:\n%s", task_id, mode, prompt_text)
        result = await asyncio.wait_for(
            connector.run_task(task=updated_task or task, workdir=workdir, mode=mode, prompt_text=prompt_text),
            timeout=timeout + 10,  # Small buffer for async overhead
        )

        logger.info("Connector returned: success=%s summary=%s", result.success, result.summary[:200])

        # 7. Save result via appropriate service
        if mode == "planning":
            from cellos.services.planning_service import save_planning_result
            from cellos.structured_response import (
                parse_planning_response,
                child_tasks_from_response,
            )

            plan_text = result.output or result.summary
            await save_planning_result(db, task_id, plan_text=plan_text, success=result.success)

            # Create child tasks from structured planning response
            structured = parse_planning_response(plan_text)
            if structured and structured.child_tasks:
                from cellos.services.task_service import TaskService as TSvc

                children_data = child_tasks_from_response(structured, task_id)
                tservice = TSvc(db)
                for child_data in children_data:
                    await tservice.create_task(**child_data)  # type: ignore[arg-type]
                    logger.info("Child task created from planning of %s", task_id)
        else:
            # Parse structured actions (child tasks) before saving execution result
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
                    await tservice.create_task(**child_data)  # type: ignore[arg-type]
                    logger.info("Child task created from execution of %s", task_id)

            from cellos.services.execution_service import save_execution_result
            exec_result = await save_execution_result(
                db, task_id, action_output or result.summary, success=result.success
            )

        # 8. Complete attempt — mark as succeeded or failed based on connector result
        final_task = await db.get_task(task_id)
        if final_task:
            status_to_use = TaskStatus.DONE if result.success else TaskStatus.FAILED
            if mode == "planning":
                await db.update_attempt(attempt.id, status_to_use)
            else:
                await db.update_attempt(
                    attempt.id, status_to_use, result_summary=exec_result.summary[:500]
                )

        logger.info("Worker completed for task %s", task_id)
        return final_task or updated_task

    except Exception as e:
        # On failure: mark attempt failed, transition task back to a recoverable state
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("Worker failed for task %s mode=%s: %s", task_id, mode, error_msg)

        if 'attempt' in locals():  # Attempt was created before failure
            try:
                await db.update_attempt(attempt.id, TaskStatus.FAILED, error_message=error_msg[:500])
            except Exception:
                logger.error("Failed to update attempt %s on error", getattr(locals().get("attempt"), "id", "?"))

        # Restore task status based on mode
        current = await db.get_task(task_id)
        if current and current.status == TaskStatus.IN_PROGRESS:
            restore_status = (
                TaskStatus.DRAFT if mode == "planning" else TaskStatus.APPROVED
            )
            restored = current.model_copy(update={
                "status": restore_status,
                "updated_at": datetime.datetime.now(),
            })
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


__all__ = ["run_task_worker", "_build_connector", "WorkerError"]
