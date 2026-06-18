"""Tests for Trello mapper module — status↔list mapping and card construction."""

from __future__ import annotations

import asyncio
import uuid

import aiosqlite
import pytest

from cellos.models import (
    AgentRole,
    CommentAuthorType,
    Task,
    TaskComment,
    TaskStatus,
)
from cellos.integrations.trello.mapper import (
    LIST_NAME_TO_KEY,
    LIST_TO_STATUSES,
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
)
from cellos.integrations.trello.models import CardAction


# ── Status ↔ List Mapping Tests ───────────────────────────────

class TestStatusToListMapping:
    def test_draft_maps_to_todo(self):
        assert status_to_list_name(TaskStatus.DRAFT) == "To Do"

    def test_needs_approval_maps_to_planning_review(self):
        assert status_to_list_name(TaskStatus.NEEDS_APPROVAL) == "Planning / Review"

    def test_approved_maps_to_doing(self):
        assert status_to_list_name(TaskStatus.APPROVED) == "Doing"

    def test_in_progress_maps_to_doing(self):
        assert status_to_list_name(TaskStatus.IN_PROGRESS) == "Doing"

    def test_done_maps_to_done(self):
        assert status_to_list_name(TaskStatus.DONE) == "Done"

    def test_failed_maps_to_done(self):
        assert status_to_list_name(TaskStatus.FAILED) == "Done"

    def test_cancelled_maps_to_done(self):
        assert status_to_list_name(TaskStatus.CANCELLED) == "Done"

    def test_blocked_maps_to_todo(self):
        assert status_to_list_name(TaskStatus.BLOCKED) == "To Do"


class TestListNameToStatuses:
    def test_todo_returns_draft_and_blocked(self):
        result = list_name_to_statuses("To Do")
        assert TaskStatus.DRAFT in result
        assert TaskStatus.BLOCKED in result

    def test_planning_review_returns_needs_approval(self):
        result = list_name_to_statuses("Planning / Review")
        assert result == [TaskStatus.NEEDS_APPROVAL]

    def test_doing_returns_approved_and_in_progress(self):
        result = list_name_to_statuses("Doing")
        assert TaskStatus.APPROVED in result
        assert TaskStatus.IN_PROGRESS in result

    def test_done_returns_terminal_statuses(self):
        result = list_name_to_statuses("Done")
        assert TaskStatus.DONE in result
        assert TaskStatus.FAILED in result
        assert TaskStatus.CANCELLED in result

    def test_unknown_list_returns_empty(self):
        result = list_name_to_statuses("Unknown List")
        assert result == []


class TestMappingConsistency:
    """Verify all 8 statuses have mappings and reverse lookups are consistent."""

    def test_all_status_values_have_mappings(self):
        for status in TaskStatus:
            name = status_to_list_name(status)
            assert name in LIST_TO_STATUSES, f"Missing reverse mapping for {name}"

    def test_roundtrip_consistency(self):
        """Status → List → Statuses should include original status."""
        for status in TaskStatus:
            list_name = status_to_list_name(status)
            statuses = list_name_to_statuses(list_name)
            assert status in statuses, (
                f"{status.value} maps to '{list_name}' but "
                f"reverse lookup doesn't include it"
            )


# ── Card Construction Tests ───────────────────────────────────

def _make_task(**kwargs):
    defaults = {
        "id": "abc123",
        "title": "Test task",
        "role": AgentRole.ENGINEER,
        "details": "Some details here.",
    }
    defaults.update(kwargs)
    return Task(**defaults)


class TestBuildCardName:
    def test_includes_role_and_title(self):
        name = build_card_name(_make_task())
        assert "[engineer]" in name
        assert "Test task" in name

    def test_architect_role(self):
        name = build_card_name(_make_task(role=AgentRole.ARCHITECT))
        assert "[architect]" in name


class TestBuildCardDesc:
    def test_includes_role_and_type(self):
        desc = build_card_desc(_make_task())
        assert "**Role:** engineer" in desc
        assert "**Type:** implementation" in desc

    def test_includes_details_section(self):
        desc = build_card_desc(_make_task(details="Important work"))
        assert "### Details" in desc
        assert "Important work" in desc

    def test_includes_success_criteria(self):
        task = _make_task(success_criteria="Tests pass")
        desc = build_card_desc(task)
        assert "### Success Criteria" in desc
        assert "Tests pass" in desc

    def test_includes_failure_criteria(self):
        task = _make_task(failure_criteria="No regressions")
        desc = build_card_desc(task)
        assert "### Failure Criteria" in desc
        assert "No regressions" in desc

    def test_includes_cellos_footer(self):
        desc = build_card_desc(_make_task())
        assert "*CelloS Task: abc123 | Updated:" in desc


# ── Comment Parsing Tests ─────────────────────────────────────

class TestParseCommentAction:
    def test_basic_comment_conversion(self):
        action = CardAction(
            id="a1", type="commentCard", date="2026-06-15T12:00:00Z",
            data={"text": "Looks good!", "card": {"id": "t1"}, "memberCreator": {"id": "m42"}}
        )
        comment = parse_comment_action(action)

        assert isinstance(comment, TaskComment)
        assert comment.content == "Looks good!"
        assert comment.author_type == CommentAuthorType.HUMAN
        assert comment.author_id == "m42"
        assert comment.task_id == "t1"


# ── KV Store Tests ───────────────────────────────────────────

@pytest.fixture
async def db_conn(tmp_path):
    """Create a temp DB with trello_sync table."""
    from cellos.persistence.schema import init_db

    db_file = tmp_path / "test.sqlite"
    await init_db(db_file)

    conn = await aiosqlite.connect(str(db_file))
    yield conn
    await conn.close()


class TestTrelloConfigKV:
    async def test_get_missing_key_returns_none(self, db_conn):
        result = await get_trello_config(db_conn, "nonexistent")
        assert result is None

    async def test_set_and_get(self, db_conn):
        await set_trello_config(db_conn, "board_id", "b123")
        result = await get_trello_config(db_conn, "board_id")
        assert result == "b123"

    async def test_overwrite_existing_value(self, db_conn):
        await set_trello_config(db_conn, "key1", "old")
        await set_trello_config(db_conn, "key1", "new")
        result = await get_trello_config(db_conn, "key1")
        assert result == "new"


class TestCardIdMapping:
    async def test_set_and_get_card_id(self, db_conn):
        task_id = "task456"
        card_id = "card789"

        await set_card_id_for_task(db_conn, task_id, card_id)
        result = await get_card_id_for_task(db_conn, task_id)

        assert result == card_id

    async def test_get_unmapped_task_returns_none(self, db_conn):
        result = await get_card_id_for_task(db_conn, "unknown")
        assert result is None


class TestListIdMapping:
    async def test_set_and_resolve_list_id_for_status(self, db_conn):
        list_id = "l_todo_123"

        from cellos.integrations.trello.mapper import TRELLO_KEY_LIST_TODO
        await set_trello_config(db_conn, TRELLO_KEY_LIST_TODO, list_id)

        result = await get_list_id_for_status(db_conn, TaskStatus.DRAFT)
        assert result == list_id

    async def test_get_all_list_ids(self, db_conn):
        from cellos.integrations.trello.mapper import (
            TRELLO_KEY_LIST_DONE,
            TRELLO_KEY_LIST_TODO,
        )

        await set_trello_config(db_conn, TRELLO_KEY_LIST_TODO, "l1")
        await set_trello_config(db_conn, TRELLO_KEY_LIST_DONE, "l2")

        result = await get_all_list_ids(db_conn)

        assert result["To Do"] == "l1"
        assert result["Done"] == "l2"


class TestListNameToKey:
    def test_all_standard_lists_have_keys(self):
        for name in ("To Do", "Planning / Review", "Doing", "Done"):
            key = LIST_NAME_TO_KEY.get(name)
            assert key is not None, f"Missing key mapping for list '{name}'"
