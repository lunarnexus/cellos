"""Status-to-list mapping, card construction, and Trello sync state helpers."""

from __future__ import annotations

import datetime
from typing import Optional

import aiosqlite

from cellos.models import CommentAuthorType, Task, TaskComment, TaskStatus
from cellos.trello.models import CardAction


# ── Status ↔ List Mapping ────────────────────────────────────────

STATUS_TO_LIST: dict[TaskStatus, str] = {
    TaskStatus.DRAFT: "To Do",
    TaskStatus.NEEDS_APPROVAL: "Planning / Review",
    TaskStatus.APPROVED: "Doing",
    TaskStatus.IN_PROGRESS: "Doing",
    TaskStatus.DONE: "Done",
    TaskStatus.FAILED: "Done",
    TaskStatus.CANCELLED: "Done",
    TaskStatus.BLOCKED: "To Do",
}

LIST_TO_STATUSES: dict[str, list[TaskStatus]] = {
    "To Do": [TaskStatus.DRAFT, TaskStatus.BLOCKED, TaskStatus.CHANGE_REQUESTED],
    "Planning / Review": [TaskStatus.NEEDS_APPROVAL],
    "Doing": [TaskStatus.APPROVED, TaskStatus.IN_PROGRESS],
    "Done": [TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED],
}


def status_to_list_name(status: TaskStatus) -> str:
    """Return the Trello list name for a given task status."""
    return STATUS_TO_LIST.get(status, "To Do")


def list_name_to_statuses(list_name: str) -> list[TaskStatus]:
    """Return possible Cellos statuses for cards moved to a given list.

    Returns an empty list if the list name is unknown (not in our mapping).
    The caller should decide whether to update the task status based on this.
    """
    return LIST_TO_STATUSES.get(list_name, [])


# ── Card Construction ────────────────────────────────────────────

def build_card_name(task: Task) -> str:
    """Build Trello card name from task: '[role] title'."""
    return f"[{task.role.value}] {task.title}"


def build_card_desc(task: Task) -> str:
    """Build markdown description for a Trello card.

    Includes role, type, details, success criteria, and CelloS task ID footer.
    """
    lines = [f"**Role:** {task.role.value} | **Type:** {task.task_type.value}", ""]

    if task.details:
        lines.extend(["### Details", task.details, ""])

    if task.success_criteria:
        lines.extend(["### Success Criteria", task.success_criteria, ""])

    if task.failure_criteria:
        lines.extend(["### Failure Criteria", task.failure_criteria, ""])

    ts = task.updated_at.strftime("%Y-%m-%d %H:%M") if task.updated_at else ""
    lines.extend([f"---", f"*CelloS Task: {task.id} | Updated: {ts}*"])

    return "\n".join(lines)


# ── Comment Parsing ──────────────────────────────────────────────

def parse_comment_action(action: CardAction) -> TaskComment:
    """Convert a Trello commentCard action into a Cellos TaskComment."""
    now = datetime.datetime.now()
    ts_str = action.date or ""

    try:
        timestamp = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else now
    except (ValueError, TypeError):
        timestamp = now

    return TaskComment(
        task_id=action.card_id or "",
        author_type=CommentAuthorType.HUMAN,
        author_id=action.member_creator_id,
        content=action.text,
        timestamp=timestamp,
    )


# ── Trello Sync KV Store Helpers ────────────────────────────────

TRELLO_KEY_BOARD_ID = "board_id"
TRELLO_KEY_LIST_TODO = "list_todo"
TRELLO_KEY_LIST_PLANNING_REVIEW = "list_planning_review"
TRELLO_KEY_LIST_DOING = "list_doing"
TRELLO_KEY_LIST_DONE = "list_done"
TRELLO_KEY_LAST_SYNC_TS = "last_sync_ts"


def _card_key(task_id: str) -> str:
    """Build the trello_sync key for a task's card ID."""
    return f"card:{task_id}"


async def get_trello_config(conn, key: str) -> Optional[str]:
    """Get a Trello config value by key from trello_sync table.

    Returns None if the key doesn't exist (not an error).
    """
    async with conn.execute(
        "SELECT value FROM trello_sync WHERE key = ?", (key,)
    ) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_trello_config(conn, key: str, value: str) -> None:
    """Upsert a Trello config value in trello_sync table."""
    async with conn.execute(
        "INSERT INTO trello_sync (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    ):
        pass


async def get_card_id_for_task(conn, task_id: str) -> Optional[str]:
    """Get the Trello card ID mapped to a Cellos task."""
    return await get_trello_config(conn, _card_key(task_id))


async def set_card_id_for_task(conn, task_id: str, card_id: str) -> None:
    """Store the mapping between a Cellos task and its Trello card."""
    await set_trello_config(conn, _card_key(task_id), card_id)


# ── List ID Mapping Helpers ───────────────────────────────────────

LIST_NAME_TO_KEY = {
    "To Do": TRELLO_KEY_LIST_TODO,
    "Planning / Review": TRELLO_KEY_LIST_PLANNING_REVIEW,
    "Doing": TRELLO_KEY_LIST_DOING,
    "Done": TRELLO_KEY_LIST_DONE,
}


async def get_list_id_for_status(conn, status: TaskStatus) -> Optional[str]:
    """Resolve the Trello list ID for a given task's current status."""
    list_name = status_to_list_name(status)
    key = LIST_NAME_TO_KEY.get(list_name)
    if not key:
        return None
    return await get_trello_config(conn, key)


async def set_list_id_for_status(conn, status: TaskStatus, list_id: str) -> None:
    """Store the Trello list ID for a given task's status."""
    list_name = status_to_list_name(status)
    key = LIST_NAME_TO_KEY.get(list_name)
    if not key:
        return
    await set_trello_config(conn, key, list_id)


async def get_all_list_ids(conn) -> dict[str, str]:
    """Get all configured Trello list IDs as a name→id mapping."""
    result = {}
    for list_name, config_key in LIST_NAME_TO_KEY.items():
        value = await get_trello_config(conn, config_key)
        if value:
            result[list_name] = value
    return result
