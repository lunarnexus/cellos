"""Trello provider — implements IntegrationProvider for Trello boards."""

from __future__ import annotations

import datetime
import logging
import os
from typing import Optional

from cellos.db import CellosDatabase
from cellos.env import env_has, get_trello_credentials
from pathlib import Path
from cellos.models import TaskStatus
from .client import TrelloClient, TrelloError
from .mapper import (
    LIST_NAME_TO_KEY,
    build_card_desc,
    build_card_name,
    get_all_list_ids,
    get_card_id_for_task,
    get_list_id_for_status,
    get_trello_config,
    list_name_to_statuses,
    parse_comment_action,
    set_card_id_for_task,
    set_trello_config,
    status_to_list_name,
    TRELLO_KEY_BOARD_ID,
)

from ..base import IntegrationProvider, IntegrationStatus, SyncDelta

logger = logging.getLogger(__name__)

SYNC_KEY_LAST_PUSH_TS = "last_push_ts"
SYNC_KEY_LAST_PULL_TS = "last_pull_ts"


def resolve_inbound_status_transition(
    current_status: TaskStatus, external_list_name: str
) -> Optional[TaskStatus]:
    """Determine the target status for a task moved to a Trello list.

    Policy (Cellos is source of truth):
    - Doing maps to IN_PROGRESS only if already APPROVED or IN_PROGRESS
    - Done maps to DONE only if APPROVED or IN_PROGRESS
    - To Do and Planning / Review never mutate Cellos status automatically

    Args:
        current_status: Current task status in Cellos.
        external_list_name: Name of the Trello list the card was moved to.

    Returns:
        Target TaskStatus, or None if no change should be applied.
    """
    possible = list_name_to_statuses(external_list_name)
    if not possible:
        return None

    target = possible[0]
    if external_list_name == "Doing":
        if current_status in (TaskStatus.DRAFT, TaskStatus.NEEDS_APPROVAL):
            return TaskStatus.IN_PROGRESS
        elif current_status == TaskStatus.APPROVED:
            return TaskStatus.IN_PROGRESS
        return None

    if external_list_name == "Done":
        if current_status in (TaskStatus.APPROVED, TaskStatus.IN_PROGRESS):
            return TaskStatus.DONE
        return None

    return target


class TrelloProvider(IntegrationProvider):
    """Trello board integration provider.

    Wraps the existing Trello client and sync service behind a generic
    IntegrationProvider interface. Cellos DB remains authoritative.
    """

    def __init__(self, db=None, config=None, _config_dir=None) -> None:
        self._db = db
        self._client = None
        self._conn = None
        self._config = config
        self._config_dir = _config_dir

    async def _get_config(self):
        if self._config is not None:
            return self._config
        from cellos.config import load_config
        cfg_dir = self._config_dir or str(Path.home() / ".cellos")
        return load_config(cfg_dir)

    @property
    def provider_name(self) -> str:
        return "trello"

    # ── Client and DB helpers ────────────────────────────────────────

    def _ensure_client(self) -> TrelloClient:
        if self._client is None:
            api_key, token = get_trello_credentials()
            self._client = TrelloClient(api_key=api_key, token=token)
        return self._client

    async def _get_db(self) -> CellosDatabase:
        if self._db is None:
            from cellos.cli import DEFAULT_DB_PATH
            db = CellosDatabase(DEFAULT_DB_PATH)
            await db.connect()
            return db
        return self._db

    async def _get_conn(self):
        if self._conn is None:
            db = await self._get_db()
            try:
                await db.connect()
            except RuntimeError:
                pass
            self._conn = db.conn
        return self._conn

    # ── Board Setup ────────────────────────────────────────────────

    async def _ensure_board(self) -> tuple[str, dict[str, str]]:
        """Ensure a Trello board is available.

        Precedence for board ID resolution:
          1. integrations.trello.board_id from config.json (primary — user-controlled).
             If set but stale/invalid, fail with clear error.
          2. Auto-create a new board and persist to config.json.

        Returns:
            Tuple of (board_id, list_ids_mapping).
        """
        conn = await self._get_conn()
        client = self._ensure_client()
        config = await self._get_config()

        # ── Step 1: Check config.json board_id ──
        cfg_board_id = config.integrations.trello.board_id
        if cfg_board_id:
            try:
                await client.get_lists(cfg_board_id)
                logger.info("Linked to existing board from config: %s", cfg_board_id)
                await set_trello_config(conn, TRELLO_KEY_BOARD_ID, cfg_board_id)
                await self._ensure_lists_exist(conn, client, cfg_board_id)
                list_ids = await get_all_list_ids(conn)
                return (cfg_board_id, list_ids)
            except TrelloError as e:
                raise RuntimeError(
                    f"Trello board '{cfg_board_id}' from config.json is inaccessible ({e}). "
                    f"Fix or clear integrations.trello.board_id in your config.json."
                )

        cfg_dir = self._config_dir or str(Path.home() / ".cellos")
        # ── Step 2: Auto-create a new board ──
        project_name = os.environ.get("CELLOS_TRELLO_PROJECT_NAME", "CelloS")
        try:
            board = await client.create_board(project_name)
        except TrelloError as e:
            logger.warning("Failed to create board '%s': %s", project_name, e)
            raise

        # Persist to config.json (primary source of truth) and SQLite for push/pull
        from cellos.config import update_trello_board_id
        update_trello_board_id(cfg_dir, board.id)
        await set_trello_config(conn, TRELLO_KEY_BOARD_ID, board.id)
        logger.info("Created Trello board: %s (%s)", board.name, board.id)

        # Create standard lists on the new board
        list_names = ["To Do", "Planning / Review", "Doing", "Done"]
        for i, name in enumerate(list_names):
            try:
                tlist = await client.create_list(board.id, name, pos=float(i))
                list_key = LIST_NAME_TO_KEY.get(name)
                if list_key:
                    await set_trello_config(conn, list_key, tlist.id)
            except TrelloError as e:
                logger.warning("Failed to create list '%s': %s", name, e)

        return board.id, await get_all_list_ids(conn)

    async def _ensure_lists_exist(
        self, conn, client: TrelloClient, board_id: str
    ) -> None:
        try:
            existing = await client.get_lists(board_id)
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
                    tlist = await client.create_list(board_id, list_name, pos=pos)
                    await set_trello_config(conn, config_key, tlist.id)
                    logger.info("Created missing list '%s' (%s)", list_name, tlist.id)
                except TrelloError as e:
                    logger.warning("Failed to create list '%s': %s", list_name, e)

    # ── IntegrationProvider Interface ────────────────────────────────

    async def is_configured(self) -> bool:
        config = await self._get_config()
        return bool(config.integrations.trello.board_id)

    async def setup(self) -> tuple[str, dict[str, str]]:
        return await self._ensure_board()

    async def status(self) -> IntegrationStatus:
        conn = await self._get_conn()
        config = await self._get_config()

        has_key = env_has("TRELLO_API_KEY")
        has_token = env_has("TRELLO_TOKEN")

        board_id = config.integrations.trello.board_id

        list_ids = await get_all_list_ids(conn)
        last_push = await get_trello_config(conn, SYNC_KEY_LAST_PUSH_TS)
        last_pull = await get_trello_config(conn, SYNC_KEY_LAST_PULL_TS)

        details: dict[str, object] = {}

        if list_ids or last_push or last_pull:
            list_mapping = {}
            for name in ("To Do", "Planning / Review", "Doing", "Done"):
                lid = list_ids.get(name, "(not mapped)")
                list_mapping[name] = lid
            details["list_mapping"] = list_mapping

        if last_push:
            details["last_push_ts"] = last_push
        if last_pull:
            details["last_pull_ts"] = last_pull

        return IntegrationStatus(
            provider_name=self.provider_name,
            configured=bool(board_id),
            credentials_configured=has_key and has_token,
            board_or_target=board_id or None,
            details=details,
        )

    async def sync(self, push: bool = True, pull: bool = True) -> SyncDelta:
        delta = SyncDelta()
        if push:
            d = await self._push_all()
            delta.items_created += d.items_created
            delta.items_updated += d.items_updated
            delta.errors.extend(d.errors)

        if pull:
            d = await self._pull_all()
            delta.comments_imported += d.comments_imported
            delta.statuses_changed += d.statuses_changed
            delta.errors.extend(d.errors)

        return delta

    async def auto_push(self) -> SyncDelta:
        return await self._push_all()

    async def auto_pull_maybe(self, pull_interval_seconds: int) -> SyncDelta:
        conn = await self._get_conn()

        last_pull_str = await get_trello_config(conn, SYNC_KEY_LAST_PULL_TS)
        now = datetime.datetime.now()

        if last_pull_str:
            try:
                last_pull = datetime.datetime.fromisoformat(last_pull_str)
                elapsed = (now - last_pull).total_seconds()
                if elapsed < pull_interval_seconds:
                    return SyncDelta()
            except ValueError:
                pass

        return await self._pull_all()

    # ── Push Logic ───────────────────────────────────────────────────

    async def _push_task(self, task) -> Optional[str]:
        conn = await self._get_conn()
        existing_card_id = await get_card_id_for_task(conn, task.id)

        board_id = await get_trello_config(conn, TRELLO_KEY_BOARD_ID)
        if not board_id:
            return None

        list_id = await get_list_id_for_status(conn, task.status)
        if not list_id:
            return None

        client = self._ensure_client()
        card_name = build_card_name(task)
        card_desc = build_card_desc(task)

        try:
            if existing_card_id:
                await client.update_card(existing_card_id, "name", card_name)
                await client.update_card(existing_card_id, "desc", card_desc)

                current_list_id = None
                cards = await client.get_all_cards_on_board(board_id)
                for c in cards:
                    if c.id == existing_card_id:
                        current_list_id = c.idList
                        break

                if current_list_id and current_list_id != list_id:
                    await client.move_card_to_list(existing_card_id, list_id)
            else:
                card = await client.create_card(list_id, card_name, card_desc)
                existing_card_id = card.id
                await set_card_id_for_task(conn, task.id, existing_card_id)

        except TrelloError as e:
            logger.error("Push failed for task %s: %s", task.id, e)
            return None

        return existing_card_id

    async def _push_all(self) -> SyncDelta:
        db = await self._get_db()
        conn = await self._get_conn()

        board_id = await get_trello_config(conn, TRELLO_KEY_BOARD_ID)
        if not board_id:
            return SyncDelta()

        delta = SyncDelta()
        tasks = await db.list_tasks()

        for task in tasks:
            try:
                existing_card_id_before = await get_card_id_for_task(conn, task.id)
                result = await self._push_task(task)
                if result:
                    if not existing_card_id_before:
                        delta.items_created += 1
                    else:
                        delta.items_updated += 1
            except TrelloError as e:
                msg = f"Task {task.id}: {e}"
                logger.debug(msg)
                delta.errors.append(str(e))

        await set_trello_config(conn, SYNC_KEY_LAST_PUSH_TS, datetime.datetime.now().isoformat())
        return delta

    # ── Pull Logic ───────────────────────────────────────────────────

    async def _pull_card_comments(self, task_id: str) -> list:
        conn = await self._get_conn()
        client = self._ensure_client()

        card_id = await get_card_id_for_task(conn, task_id)
        if not card_id:
            return []

        last_pull_ts = await get_trello_config(conn, SYNC_KEY_LAST_PULL_TS) or ""

        try:
            actions = await client.get_card_actions(card_id)
        except TrelloError as e:
            logger.error("Failed to fetch comments for task %s: %s", task_id, e)
            return []

        db = await self._get_db()
        imported = []
        existing_comments = await db.list_comments(task_id)
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
                await db.create_comment(
                    task_id, comment.author_type, comment.content, author_id=comment.author_id
                )
                imported.append(comment)
                existing_texts.add(comment.content)
            except Exception as e:
                logger.error("Failed to import comment for task %s: %s", task_id, e)

        return imported

    async def _detect_list_moves(self):
        conn = await self._get_conn()
        client = self._ensure_client()

        board_id = await get_trello_config(conn, TRELLO_KEY_BOARD_ID)
        if not board_id:
            return []

        try:
            cards = await client.get_all_cards_on_board(board_id)
        except TrelloError as e:
            logger.error("Failed to fetch cards for list move detection: %s", e)
            return []

        db = await self._get_db()
        list_ids = await get_all_list_ids(conn)
        id_to_name = {v: k for k, v in list_ids.items()}

        moves = []
        tasks = await db.list_tasks()

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

            target = resolve_inbound_status_transition(task.status, list_name)
            if target and target != task.status:
                moves.append((task.id, target))

        return moves

    async def _pull_all(self) -> SyncDelta:
        db = await self._get_db()
        conn = await self._get_conn()

        delta = SyncDelta()

        tasks = await db.list_tasks()
        for task in tasks:
            comments = await self._pull_card_comments(task.id)
            delta.comments_imported += len(comments)

        moves = await self._detect_list_moves()
        for task_id, target_status in moves:
            try:
                current = await db.get_task(task_id)
                if not current or current.status == target_status:
                    continue

                await db.update_task(
                    current.model_copy(
                        update={"status": target_status, "updated_at": datetime.datetime.now()}
                    )
                )
                delta.statuses_changed += 1
            except Exception as e:
                logger.error("Failed to apply list move for task %s: %s", task_id, e)
                delta.errors.append(str(e))

        await set_trello_config(
            conn, SYNC_KEY_LAST_PULL_TS, datetime.datetime.now().isoformat()
        )
        return delta
