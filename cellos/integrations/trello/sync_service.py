"""Bidirectional sync between CelloS tasks and Trello cards."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Optional

from cellos.db import CellosDatabase
from cellos.env import get_trello_credentials
from cellos.models import Task, TaskComment, TaskStatus
from cellos.integrations.trello.client import TrelloClient, TrelloError
from cellos.integrations.trello.mapper import (
    LIST_NAME_TO_KEY,
    STATUS_TO_LIST,
    build_card_desc,
    build_card_name,
    get_all_list_ids,
    get_card_id_for_task,
    get_list_id_for_status,
    get_trello_config,
    list_name_to_statuses,
    parse_comment_action,
    set_card_id_for_task,
    set_list_id_for_status,
    set_trello_config,
    status_to_list_name,
    TRELLO_KEY_BOARD_ID,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncDelta:
    """Structured result of a sync operation."""

    cards_created: int = 0
    cards_updated: int = 0
    cards_moved: int = 0
    comments_imported: int = 0
    statuses_changed: int = 0
    errors: list[str] = field(default_factory=list)


class TrelloSyncService:
    """Bidirectional sync logic between CelloS tasks and Trello cards.

    Cellos DB is the authoritative source of truth. Sync pushes task changes to
    Trello (cards, descriptions, list movement) and pulls comments/list moves
    back from Trello into Cellos.
    """

    def __init__(self, client: Optional[TrelloClient] = None, db: Optional[CellosDatabase] = None):
        self._client = client or TrelloClient.from_env()
        self.db = db
        self._conn = None

    @property
    def client(self) -> TrelloClient:
        return self._client

    async def _get_conn(self):
        if self._conn is None and self.db:
            try:
                await self.db.connect()
            except RuntimeError:
                pass
            self._conn = self.db.conn
        return self._conn or self.db.conn  # type: ignore[union-attr]

    # ── Board Setup ───────────────────────────────────────────────

    async def ensure_board(self) -> tuple[str, dict[str, str]]:
        """Ensure a Trello board exists with the required lists.

        If no board ID configured, auto-create one. If board ID provided,
        validate it exists and has required lists (create missing ones).

        Returns:
            Tuple of (board_id, list_ids_map) where list_ids_map is
            {list_name: trello_list_id}.
        """
        conn = await self._get_conn()
        board_id = await get_trello_config(conn, TRELLO_KEY_BOARD_ID)

        if not board_id:
            board_id = await self._create_board_and_lists(conn)
        else:
            await self._ensure_lists_exist(conn, board_id)

        list_ids = await get_all_list_ids(conn)
        return (board_id, list_ids)

    async def _create_board_and_lists(self, conn) -> str:
        """Create a new Trello board and its 4 standard lists."""
        import os

        project_name = os.environ.get("CELLOS_TRELLO_PROJECT_NAME", "CelloS")
        try:
            board = await self.client.create_board(project_name)
        except TrelloError as e:
            logger.warning("Failed to create board '%s': %s", project_name, e)
            raise

        await set_trello_config(conn, TRELLO_KEY_BOARD_ID, board.id)
        logger.info("Created Trello board: %s (%s)", board.name, board.id)

        list_names = ["To Do", "Planning / Review", "Doing", "Done"]
        for i, name in enumerate(list_names):
            try:
                tlist = await self.client.create_list(board.id, name, pos=float(i))
                list_key = LIST_NAME_TO_KEY.get(name)
                if list_key:
                    await set_trello_config(conn, list_key, tlist.id)
                logger.info("Created list '%s' (%s)", name, tlist.id)
            except TrelloError as e:
                logger.warning("Failed to create list '%s': %s", name, e)

        return board.id

    async def _ensure_lists_exist(self, conn, board_id: str) -> None:
        """Validate existing lists and create any missing ones."""
        try:
            existing = await self.client.get_lists(board_id)
        except TrelloError as e:
            logger.warning("Cannot access board %s: %s", board_id, e)
            raise

        existing_map = {l.name.lower(): l for l in existing}

        for list_name, config_key in LIST_NAME_TO_KEY.items():
            stored_id = await get_trello_config(conn, config_key)

            if not stored_id and list_name.lower() in existing_map:
                tlist = existing_map[list_name.lower()]
                await set_trello_config(conn, config_key, tlist.id)
                logger.info("Discovered missing list '%s' (%s)", list_name, tlist.id)
                continue

            if not stored_id and list_name.lower() not in existing_map:
                try:
                    pos = float(len(existing)) + 1
                    tlist = await self.client.create_list(board_id, list_name, pos=pos)
                    await set_trello_config(conn, config_key, tlist.id)
                    logger.info("Created missing list '%s' (%s)", list_name, tlist.id)
                except TrelloError as e:
                    logger.warning("Failed to create list '%s': %s", list_name, e)

    # ── Push (Cellos → Trello) ─────────────────────────────────────

    async def push_task(self, task: Task) -> Optional[str]:
        """Create or update a single task's card on Trello.

        Returns the card ID if successful, None if task is in a terminal state.
        """
        conn = await self._get_conn()
        existing_card_id = await get_card_id_for_task(conn, task.id)
        board_id = await get_trello_config(conn, TRELLO_KEY_BOARD_ID)

        if not board_id:
            logger.debug("No Trello board configured for push")
            return None

        list_id = await get_list_id_for_status(conn, task.status)
        if not list_id:
            logger.debug("No list mapped for status %s", task.status)
            return None

        card_name = build_card_name(task)
        card_desc = build_card_desc(task)

        try:
            if existing_card_id:
                await self.client.update_card(existing_card_id, "name", card_name)
                await self.client.update_card(existing_card_id, "desc", card_desc)

                current_list_id = None
                cards = await self.client.get_all_cards_on_board(board_id)
                for c in cards:
                    if c.id == existing_card_id:
                        current_list_id = c.idList
                        break

                if current_list_id and current_list_id != list_id:
                    await self.client.move_card_to_list(existing_card_id, list_id)
            else:
                card = await self.client.create_card(list_id, card_name, card_desc)
                existing_card_id = card.id
                await set_card_id_for_task(conn, task.id, existing_card_id)

        except TrelloError as e:
            logger.error("Push failed for task %s: %s", task.id, e)
            return None

        return existing_card_id

    async def push_all(self) -> SyncDelta:
        """Sync all tasks to Trello. Returns counts of changes made."""
        if not self.db:
            return SyncDelta()

        conn = await self._get_conn()
        board_id = await get_trello_config(conn, TRELLO_KEY_BOARD_ID)
        if not board_id:
            logger.info("No Trello board configured — skipping push")
            return SyncDelta()

        delta = SyncDelta()
        tasks = await self.db.list_tasks()

        for task in tasks:
            try:
                result = await self.push_task(task)
                if result:
                    existing_card_id = await get_card_id_for_task(conn, task.id)
                    if not existing_card_id:
                        delta.cards_created += 1
                    else:
                        delta.cards_updated += 1
            except TrelloError as e:
                msg = f"Task {task.id}: {e}"
                logger.debug(msg)
                delta.errors.append(str(e))

        await set_trello_config(conn, "last_push_ts", datetime.datetime.now().isoformat())
        return delta

    # ── Pull (Trello → Cellos) ─────────────────────────────────────

    async def pull_card_comments(self, task_id: str) -> list[TaskComment]:
        """Fetch new comment actions for a task's card and import them."""
        conn = await self._get_conn()
        card_id = await get_card_id_for_task(conn, task_id)
        if not card_id:
            return []

        last_pull_ts = await get_trello_config(conn, "last_pull_ts") or ""

        try:
            actions = await self.client.get_card_actions(card_id)
        except TrelloError as e:
            logger.error("Failed to fetch comments for task %s: %s", task_id, e)
            return []

        imported = []
        existing_comments = await self.db.list_comments(task_id)
        existing_texts = {c.content for c in existing_comments}

        for action in actions:
            if action.type != "commentCard":
                continue
            if not action.text:
                continue
            if last_pull_ts and action.date < last_pull_ts:
                continue
            if action.text in existing_texts:
                continue

            comment = parse_comment_action(action)
            comment.task_id = task_id
            try:
                await self.db.create_comment(
                    task_id, comment.author_type, comment.content, author_id=comment.author_id
                )
                imported.append(comment)
                existing_texts.add(comment.content)
            except Exception as e:
                logger.error("Failed to import comment for task %s: %s", task_id, e)

        return imported

    async def detect_list_moves(self) -> list[tuple[str, TaskStatus]]:
        """Detect cards moved to a different list than expected.

        Returns list of (task_id, suggested_new_status) tuples for tasks whose
        cards were moved on Trello but not yet reflected in Cellos DB.
        Only suggests moves toward "Doing" or "Done", never auto-approves.
        """
        conn = await self._get_conn()
        board_id = await get_trello_config(conn, TRELLO_KEY_BOARD_ID)
        if not board_id:
            return []

        try:
            cards = await self.client.get_all_cards_on_board(board_id)
        except TrelloError as e:
            logger.error("Failed to fetch cards for list move detection: %s", e)
            return []

        list_ids = await get_all_list_ids(conn)
        id_to_name = {v: k for k, v in list_ids.items()}

        moves = []
        tasks = await self.db.list_tasks()

        card_map = {}
        for task in tasks:
            card_id = await get_card_id_for_task(conn, task.id)
            if card_id:
                card_map[card_id] = task

        for card in cards:
            task = card_map.get(card.id)
            if not task:
                continue

            list_name = id_to_name.get(card.idList)
            if not list_name:
                continue

            expected_list_name = status_to_list_name(task.status)
            if list_name == expected_list_name:
                continue

            possible_statuses = list_name_to_statuses(list_name)
            for s in possible_statuses:
                moves.append((task.id, s))
                break

        return moves

    async def pull_all(self) -> SyncDelta:
        """Run all pull operations. Returns structured result with counts."""
        if not self.db:
            return SyncDelta()

        delta = SyncDelta()

        tasks = await self.db.list_tasks()
        for task in tasks:
            comments = await self.pull_card_comments(task.id)
            delta.comments_imported += len(comments)

        moves = await self.detect_list_moves()
        for task_id, new_status in moves:
            try:
                if new_status == TaskStatus.IN_PROGRESS:
                    target = TaskStatus.APPROVED
                elif new_status == TaskStatus.DONE:
                    existing_task = await self.db.get_task(task_id)
                    target = TaskStatus.DONE if existing_task else new_status

                current = await self.db.get_task(task_id)
                if not current or current.status == target:
                    continue

                await self.db.update_task(current.model_copy(
                    update={"status": target, "updated_at": datetime.datetime.now()}
                ))
                delta.statuses_changed += 1
            except Exception as e:
                logger.error("Failed to apply list move for task %s: %s", task_id, e)
                delta.errors.append(str(e))

        await set_trello_config(
            await self._get_conn(), "last_pull_ts", datetime.datetime.now().isoformat()
        )
        return delta
